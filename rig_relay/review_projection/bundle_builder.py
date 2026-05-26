from __future__ import annotations

import datetime
import hashlib
from pathlib import Path
import zipfile

from rig_relay.core.paths import is_confidential_artifact_path
from rig_relay.review_projection.models import (
    BundleManifest,
    DisclosureReceipt,
    LocalCrosswalk,
)
from rig_relay.review_projection.protected_content import (
    ContentKind,
    build_default_manifest,
    build_selector_entries,
    seal_manifest,
    write_manifest_json,
)


def deterministic_zip_write(zip_path: Path, files_content: dict[str, str]) -> str:
    """Writes a deterministic ZIP archive and returns its SHA256 hash.
    Fixed permissions and timestamps.
    """
    fixed_time = (2026, 1, 1, 0, 0, 0)
    hasher = hashlib.sha256()

    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for rel_path in sorted(files_content.keys()):
            content = files_content[rel_path].encode("utf-8")
            zinfo = zipfile.ZipInfo(rel_path, fixed_time)
            # -rw-r--r-- permissions
            zinfo.external_attr = 0o644 << 16
            zf.writestr(zinfo, content)

    with open(zip_path, "rb") as f:
        while chunk := f.read(8192):
            hasher.update(chunk)

    return hasher.hexdigest()


class BundleBuilder:
    def __init__(self, output_dir: Path):
        self.output_dir = output_dir
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def write_bundle(
        self,
        projection_id: str,
        files_content: dict[str, str],
        bundle_manifest: BundleManifest,
        crosswalk: LocalCrosswalk,
        receipt: DisclosureReceipt,
    ) -> None:
        repo_root = (
            self.output_dir.parents[2]
            if len(self.output_dir.parents) >= 3
            else Path.cwd()
        )
        for rel_path in files_content:
            if is_confidential_artifact_path(Path(rel_path), repo_root):
                raise ValueError(
                    "confidential_artifact_refused:review_projection_bundle"
                )

        # ── Crosswalk prohibition (structural enforcement) ─────────
        _CROSSWALK_SENTINELS = frozenset({
            "crosswalk",
            "local_crosswalk",
            "pseudonym_map",
        })
        for rel_path in files_content:
            path_lower = rel_path.lower()
            for sentinel in _CROSSWALK_SENTINELS:
                if sentinel in path_lower:
                    raise ValueError(
                        "crosswalk_material_refused:review_projection_bundle — "
                        "Crosswalk material is prohibited from bundle export."
                    )
        for content in files_content.values():
            content_lower = content.lower()
            for sentinel in _CROSSWALK_SENTINELS:
                if sentinel in content_lower:
                    raise ValueError(
                        "crosswalk_material_refused:review_projection_bundle — "
                        "Crosswalk material detected in file content."
                    )

        # 1. Bundle Manifest into the ZIP content map
        files_content["bundle_manifest.json"] = bundle_manifest.model_dump_json(
            indent=2
        )

        # 2. Write deterministic ZIP
        zip_path = self.output_dir / f"review_projection_{projection_id}.zip"
        zip_hash = deterministic_zip_write(zip_path, files_content)

        # 3. Update Crosswalk and Receipt with ZIP info
        crosswalk.candidate_zip_hash = zip_hash
        receipt.candidate_zip_path = str(zip_path.resolve())
        receipt.candidate_zip_sha256 = zip_hash

        # 4. Hash crosswalk for receipt (never the content itself)
        cw_json = crosswalk.model_dump_json(indent=2)
        cw_hash = hashlib.sha256(cw_json.encode("utf-8")).hexdigest()
        receipt.crosswalk_hash = cw_hash

        # 5. Write separate local files
        cw_path = self.output_dir / f"crosswalk_{projection_id}.json"
        cw_path.write_text(cw_json, "utf-8")

        rcpt_path = self.output_dir / f"receipt_{projection_id}.json"
        rcpt_path.write_text(receipt.model_dump_json(indent=2), "utf-8")

        # 6. Build and write protected-content manifest
        now_iso = datetime.datetime.now(datetime.UTC).isoformat() + "Z"
        source_digest = receipt.head_sha or "unknown"
        manifest = build_default_manifest(
            projection_id=projection_id,
            bundle_digest=zip_hash,
            source_digest=source_digest,
            created_at=now_iso,
        )
        manifest.count_retained_projected = len(files_content)
        manifest.total_items = len(files_content)

        # Populate selectors from pseudonymized crosswalk identities
        pseudonymized = sorted(set(crosswalk.mappings.values()))
        source_identifiers = [p for p in pseudonymized if not p.startswith("STR_")]
        string_literals = [p for p in pseudonymized if p.startswith("STR_")]

        if source_identifiers:
            selectors = build_selector_entries(
                pseudonymized_names=source_identifiers,
                content_kind=ContentKind.SOURCE_IDENTIFIER.value,
                disclosure_class="commit_body",
            )
            manifest.selectors = selectors

        if string_literals:
            lit_selectors = build_selector_entries(
                pseudonymized_names=string_literals,
                content_kind=ContentKind.SOURCE_STRING_LITERAL.value,
                disclosure_class="commit_body",
            )
            manifest.selectors.extend(lit_selectors)

        # Truthful accounting: counts must reflect observed items
        manifest.count_pseudonymized_disclosable = len(source_identifiers)
        manifest.count_hash_evidence_only = len(string_literals)
        manifest.total_items = (
            manifest.count_retained_projected
            + manifest.count_pseudonymized_disclosable
            + manifest.count_hash_evidence_only
            + manifest.count_prohibited
        )
        kinds = {ContentKind.BUNDLE_METADATA.value}
        if source_identifiers:
            kinds.add(ContentKind.SOURCE_IDENTIFIER.value)
        if string_literals:
            kinds.add(ContentKind.SOURCE_STRING_LITERAL.value)
        manifest.content_kinds_present = sorted(kinds)

        # Seal after all final fields and selectors are populated
        seal_manifest(manifest)

        manifest_path = (
            self.output_dir / f"protected_content_manifest_{projection_id}.json"
        )
        write_manifest_json(manifest, str(manifest_path))
        receipt.candidate_zip_sha256 = zip_hash
