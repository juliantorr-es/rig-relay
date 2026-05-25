from __future__ import annotations

import hashlib
from pathlib import Path
import zipfile

from rig_relay.core.paths import is_confidential_artifact_path
from rig_relay.review_projection.models import (
    BundleManifest,
    DisclosureReceipt,
    LocalCrosswalk,
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
