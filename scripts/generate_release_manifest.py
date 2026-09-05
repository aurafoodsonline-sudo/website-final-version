from __future__ import annotations

import argparse
import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "outputs" / "RELEASE_MANIFEST.json"
EXCLUDED = {".git", ".venv", "__pycache__", ".pytest_cache", "staticfiles", "media", "backups", "work", "sources", "outputs", "portal-source"}
EXCLUDED_RELATIVE_PATHS = {
    "docs/FINAL_RELEASE_CERTIFICATION.md", "docs/FOUR_DOMAIN_EXTENSION.md",
    "docs/FOUR_DOMAIN_SCORECARD.md", "docs/IMPLEMENTATION_STATUS.md",
    "docs/SCORECARD_56_DOMAINS.md", "docs/SECOND_PASS_RELEASE_AUDIT.md",
    "docs/STRICT_COMPLIANCE_AUDIT.md",
}
PRIVATE_KEY_SUFFIXES = {".pem", ".key", ".p12", ".pfx", ".jks"}
PRIVATE_KEY_NAMES = {"id_rsa", "id_ed25519"}


def sha256(path):
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--release", type=Path)
    args = parser.parse_args()
    files = []
    candidates = []
    for current, directories, filenames in os.walk(ROOT):
        directories[:] = [name for name in directories if name not in EXCLUDED]
        candidates.extend(Path(current) / filename for filename in filenames)
    for path in sorted(candidates):
        if path.relative_to(ROOT).as_posix() in EXCLUDED_RELATIVE_PATHS:
            continue
        if (
            path.suffix.lower() in {".pyc", ".sqlite3", ".db", ".log", ".zip", ".sha256"} | PRIVATE_KEY_SUFFIXES
            or path.name == ".env"
            or path.name.lower() in PRIVATE_KEY_NAMES
        ):
            continue
        files.append({"path": path.relative_to(ROOT).as_posix(), "sha256": sha256(path), "size": path.stat().st_size})
    release = None
    if args.release and args.release.exists():
        release = {"filename": args.release.name, "sha256": sha256(args.release), "size": args.release.stat().st_size}
    document = {
        "schema": "aurafoods-release-manifest/v1", "generated_at": datetime.now(timezone.utc).isoformat(),
        "release": release,
        "payload": {"algorithm": "SHA-256", "file_count": len(files), "files": files},
        "note": "The detached manifest and .sha256 file authenticate the final archive; embedding its own final hash would be self-referential.",
    }
    OUT.parent.mkdir(exist_ok=True)
    OUT.write_text(json.dumps(document, indent=2), encoding="utf-8")
    print(OUT)


if __name__ == "__main__":
    main()
