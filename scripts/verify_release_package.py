from __future__ import annotations

import argparse
import hashlib
import json
import zipfile
from pathlib import Path, PurePosixPath


REQUIRED = {
    ".env.example", "Dockerfile", "README.md", "docker-compose.yml", "manage.py",
    "requirements.txt", "docs/UNIFIED_DEPLOYMENT_RUNBOOK.md",
    "erp/migrations/0001_initial.py", "shop/migrations/0001_initial.py",
    "sales/migrations/0001_initial.py", "crm/migrations/0001_initial.py",
    "outputs/sbom.cdx.json", "outputs/RELEASE_MANIFEST.json",
}
PRIVATE_SUFFIXES = {".pem", ".key", ".p12", ".pfx", ".jks"}
PRIVATE_NAMES = {"id_rsa", "id_ed25519"}


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def verify(archive_path: Path, manifest_path: Path | None = None, checksum_path: Path | None = None) -> None:
    archive_bytes = archive_path.read_bytes()
    if checksum_path:
        expected = checksum_path.read_text(encoding="ascii").split()[0]
        if digest(archive_bytes) != expected:
            raise SystemExit("Release checksum mismatch.")
    if manifest_path:
        detached = json.loads(manifest_path.read_text(encoding="utf-8"))
        release = detached.get("release") or {}
        if release.get("sha256") != digest(archive_bytes) or release.get("size") != len(archive_bytes):
            raise SystemExit("Detached manifest does not authenticate the archive.")

    with zipfile.ZipFile(archive_path) as archive:
        names = set(archive.namelist())
        for name in names:
            path = PurePosixPath(name)
            if path.is_absolute() or ".." in path.parts or "\\" in name:
                raise SystemExit(f"Unsafe archive path: {name}")
            if path.name == ".env" or path.name.lower() in PRIVATE_NAMES or path.suffix.lower() in PRIVATE_SUFFIXES:
                raise SystemExit(f"Private artifact in archive: {name}")
        missing = REQUIRED - names
        if missing:
            raise SystemExit("Release is missing required files: " + ", ".join(sorted(missing)))

        embedded = json.loads(archive.read("outputs/RELEASE_MANIFEST.json"))
        entries = embedded.get("payload", {}).get("files", [])
        if embedded.get("payload", {}).get("file_count") != len(entries):
            raise SystemExit("Embedded manifest file count is inconsistent.")
        for entry in entries:
            name = entry["path"]
            if name not in names:
                raise SystemExit(f"Manifest entry missing from archive: {name}")
            data = archive.read(name)
            if len(data) != entry["size"] or digest(data) != entry["sha256"]:
                raise SystemExit(f"Manifest mismatch for {name}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("archive", type=Path)
    parser.add_argument("--manifest", type=Path)
    parser.add_argument("--checksum", type=Path)
    args = parser.parse_args()
    verify(args.archive, args.manifest, args.checksum)
    print(f"Verified {args.archive}")


if __name__ == "__main__":
    main()
