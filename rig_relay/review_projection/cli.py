from __future__ import annotations

import argparse
import datetime
import hashlib
import json
import os
from pathlib import Path
import uuid
import zipfile

from rig_relay.core.paths import (
    is_confidential_artifact_path,
    refuse_confidential_input,
)
from rig_relay.review_projection.bundle_builder import BundleBuilder
from rig_relay.review_projection.classification import ClassificationEngine
from rig_relay.review_projection.models import (
    BundleManifest,
    DisclosureReceipt,
    FileClassification,
    InclusionManifest,
    LocalCrosswalk,
)
from rig_relay.review_projection.policy import PolicyEngine
from rig_relay.review_projection.public_baseline import PublicBaselineValidator
from rig_relay.review_projection.residual_scanner import ResidualRiskScanner
from rig_relay.review_projection.transformer import PythonTransformer


def _get_git_info(repo_root: Path) -> tuple[str, str]:
    from rig_relay.review_projection.provenance import ProjectionSnapshot

    try:
        snapshot = ProjectionSnapshot(repo_root)
    except Exception:
        return "unknown", "unknown"
    return snapshot.branch or "detached", snapshot.head_sha


def _run_projection(
    repo_root: Path,
    manifest_path: Path,
    emit_bundle: bool,
    public_attestation_path: Path | None = None,
    local_rules_path: Path | None = None,
) -> None:
    # 1. Load configuration
    allowed, reason = refuse_confidential_input(
        manifest_path, "review_projection_manifest", repo_root
    )
    if not allowed:
        print(f"Refusing inclusion manifest: {reason}")
        return

    try:
        manifest_data = json.loads(manifest_path.read_text("utf-8"))
        manifest = InclusionManifest.model_validate(manifest_data)
    except Exception as e:
        print(f"Failed to load inclusion manifest: {e}")
        return

    policy_engine = PolicyEngine(local_rules_path)
    public_validator = PublicBaselineValidator(public_attestation_path)

    # 2. Setup engines
    classifier = ClassificationEngine(
        repo_root, policy_engine, manifest, public_validator
    )
    transformer = PythonTransformer()
    output_dir = repo_root / ".build" / "rig-relay" / "review_projection"
    allowed, reason = refuse_confidential_input(
        output_dir, "review_projection_output", repo_root
    )
    if not allowed:
        print(f"Refusing projection output directory: {reason}")
        return
    builder = BundleBuilder(output_dir)

    projection_id = str(uuid.uuid4())
    branch, head_sha = _get_git_info(repo_root)

    receipt = DisclosureReceipt(
        projection_id=projection_id,
        mode=manifest.mode,
        created_at=datetime.datetime.now(datetime.UTC).isoformat() + "Z",
        source_root_fingerprint=str(repo_root.resolve()),
        branch=branch,
        head_sha=head_sha,
        public_baseline_status="verified" if public_attestation_path else "none",
        policy_version="1.0",
        input_file_count=0,
        classification_counts={},
        included_path_hashes=[],
        excluded_path_hashes={},
        applied_rules=[],
        crosswalk_hash="",
        residual_scan_result="pending",
        output_status="classification_incomplete",
    )

    crosswalk = LocalCrosswalk(projection_id=projection_id)
    bundle_manifest = BundleManifest(mode=manifest.mode)

    files_to_zip: dict[str, str] = {}

    classification_counts: dict[str, int] = {k.value: 0 for k in FileClassification}

    # 3. Traversal (simple recursive for v1)
    input_count = 0
    for root, dirs, files in os.walk(repo_root):
        # Exclude common dirs to speed up traversal
        dirs[:] = [
            d for d in dirs if d not in (".git", "node_modules", ".venv", "__pycache__")
        ]
        dirs[:] = [
            d
            for d in dirs
            if not is_confidential_artifact_path(Path(root) / d, repo_root)
        ]

        for file in files:
            file_path = Path(root) / file
            input_count += 1
            classification = classifier.classify_file(file_path)
            cls_val = classification.value
            classification_counts[cls_val] = classification_counts.get(cls_val, 0) + 1

            try:
                rel_path_str = str(file_path.relative_to(repo_root))
            except Exception:
                continue

            file_hash = classifier._hash_file(file_path)

            if classification in (
                FileClassification.TRANSFORM_ALLOWED,
                FileClassification.PUBLIC_ALREADY_DISCLOSED,
            ):
                if file_path.suffix == ".py":
                    source = file_path.read_text("utf-8")
                    try:
                        transformed_source, mapping = transformer.transform(source)
                        files_to_zip[rel_path_str] = transformed_source
                        crosswalk.mappings.update(mapping)
                        receipt.included_path_hashes.append(file_hash)
                        bundle_manifest.transformed_files.append(rel_path_str)
                    except Exception:
                        # Fallback to excluded if transform fails
                        receipt.excluded_path_hashes[file_hash] = (
                            "transformation_failed"
                        )
                        classification_counts[
                            FileClassification.UNCLASSIFIED_REFUSED.value
                        ] += 1
                else:
                    # v1 only supports python files
                    receipt.excluded_path_hashes[file_hash] = "unsupported_file_type"
            else:
                receipt.excluded_path_hashes[file_hash] = classification.value
                crosswalk.excluded_concrete_paths.append(rel_path_str)

    receipt.input_file_count = input_count
    receipt.classification_counts = classification_counts
    bundle_manifest.excluded_counts = {
        k: v
        for k, v in classification_counts.items()
        if k
        not in (
            FileClassification.TRANSFORM_ALLOWED.value,
            FileClassification.PUBLIC_ALREADY_DISCLOSED.value,
        )
    }

    if not emit_bundle:
        receipt.output_status = "refused"
        receipt.residual_scan_result = "dry_run"
        print(
            f"Classification complete. Dry-run only. {len(files_to_zip)} files ready for transformation."
        )
        return

    # 4. Residual Risk Scan
    scanner = ResidualRiskScanner(crosswalk.mappings, str(repo_root.resolve()))
    for _rel_path, content in files_to_zip.items():
        scan_result = scanner.scan(content)
        if scan_result:
            receipt.output_status = "refused"
            receipt.residual_scan_result = scan_result
            # Write receipt and crosswalk but no zip
            cw_json = crosswalk.model_dump_json(indent=2)
            receipt.crosswalk_hash = hashlib.sha256(cw_json.encode("utf-8")).hexdigest()
            output_dir.mkdir(parents=True, exist_ok=True)
            (output_dir / f"receipt_{projection_id}.json").write_text(
                receipt.model_dump_json(indent=2)
            )
            (output_dir / f"crosswalk_{projection_id}.json").write_text(cw_json)
            print(f"Residual risk scan failed: {scan_result}")
            return

    receipt.residual_scan_result = "passed"
    receipt.output_status = "candidate_generated"

    # 5. Build bundle
    try:
        builder.write_bundle(
            projection_id, files_to_zip, bundle_manifest, crosswalk, receipt
        )
    except ValueError as e:
        print(f"Projection bundle refused: {e}")
        return
    print(f"Candidate ZIP generated: review_projection_{projection_id}.zip")


def _run_diff_projection(repo_root: Path) -> None:
    from rig_relay.review_projection.diff_bundler import DiffBundler

    print(f"Repository root: {repo_root}")
    print("Generating diff projection bundle (HEAD vs working tree)...")

    bundler = DiffBundler(repo_root)
    result = bundler.build()

    if result.refused:
        print(f"Projection refused: {result.refusal_reason}")
        print(f"Files excluded: {result.files_excluded}")
        print(f"Files refused: {result.files_refused}")
        if result.scan_findings_path and result.scan_findings_path.is_file():
            print(f"Scan findings: {result.scan_findings_path}")
        return

    print(f"Projection ID: {result.projection_id}")
    print(f"Files included: {result.files_included}")
    print(f"Files excluded: {result.files_excluded}")
    print(f"Files refused: {result.files_refused}")
    if result.zip_path:
        print(f"Candidate ZIP: {result.zip_path}")
        print(f"ZIP SHA256: {result.zip_sha256}")
    if result.receipt_path:
        print(f"Compilation receipt: {result.receipt_path}")
    if result.crosswalk_path:
        print(f"Local crosswalk (never export): {result.crosswalk_path}")
    if result.scan_findings_path:
        print(f"Local scan findings (never export): {result.scan_findings_path}")
    print("\nDisclosure target: LOCAL_CANDIDATE_NO_DISCLOSURE")
    print("No disclosure has occurred. This is a local candidate bundle only.")
    print(
        "To disclose, you must explicitly approve the exact bundle hash and record recipient details."
    )


def _verify_bundle(zip_path: Path) -> None:
    if not zip_path.is_file():
        print("ZIP file not found.")
        return

    try:
        with zipfile.ZipFile(zip_path, "r") as zf:
            names = zf.namelist()
            if "bundle_manifest.json" not in names:
                print("Verification failed: bundle_manifest.json missing.")
                return

            # Read manifest without extracting
            with zf.open("bundle_manifest.json") as f:
                manifest_data = json.loads(f.read().decode("utf-8"))

            if (
                manifest_data.get("schema_version")
                != "rig.review_projection.bundle_manifest.v1"
            ):
                print("Verification failed: invalid manifest schema.")
                return

            # Check crosswalk exclusion
            if any("crosswalk" in name.lower() for name in names):
                print("Verification failed: crosswalk found inside ZIP.")
                return

        print("Verification passed: Inspect-only ZIP verification successful.")
    except Exception as e:
        print(f"Verification failed: {e}")


def main():
    parser = argparse.ArgumentParser(prog="review_projection")
    subparsers = parser.add_subparsers(dest="command", required=True)

    # Classify / Project
    p_proj = subparsers.add_parser("project")
    p_proj.add_argument("--repo-root", type=Path, default=Path.cwd())
    p_proj.add_argument("--manifest", type=Path, required=True)
    p_proj.add_argument("--public-attestation", type=Path)
    p_proj.add_argument("--local-rules", type=Path)
    p_proj.add_argument("--emit-candidate-bundle", action="store_true")

    # Verify
    p_verify = subparsers.add_parser("verify")
    p_verify.add_argument("--zip-path", type=Path, required=True)

    # Diff projection (HEAD vs working tree)
    p_diff = subparsers.add_parser(
        "diff", help="Generate a sanitized diff bundle from HEAD to working tree"
    )
    p_diff.add_argument(
        "--repo-root", type=Path, default=Path.cwd(), help="Repository root directory"
    )
    p_diff.add_argument(
        "--disclosure-target",
        type=str,
        default="LOCAL_CANDIDATE_NO_DISCLOSURE",
        choices=[
            "LOCAL_CANDIDATE_NO_DISCLOSURE",
            "EXTERNAL_AI_REVIEWER_CONTROLLED_ACCOUNT",
            "HUMAN_REVIEWER_CONFIDENTIALITY_DUTY",
            "PRIVATE_REPOSITORY_REVIEWER_ACCESS",
            "OTHER_APPROVED_RECIPIENT",
        ],
        help="Disclosure target class",
    )

    args = parser.parse_args()

    if args.command == "project":
        _run_projection(
            args.repo_root,
            args.manifest,
            args.emit_candidate_bundle,
            args.public_attestation,
            args.local_rules,
        )
    elif args.command == "verify":
        _verify_bundle(args.zip_path)
    elif args.command == "diff":
        _run_diff_projection(args.repo_root)


if __name__ == "__main__":
    main()
