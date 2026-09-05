from __future__ import annotations

import argparse
import hashlib
import os
import subprocess
import sys
import zipfile
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
DEFAULT_OUT = ROOT / "outputs" / "aurafoods_unified_release.zip"
EXCLUDED_PARTS = {".git", ".venv", "__pycache__", ".pytest_cache", "staticfiles", "media", "backups", "work", "sources", "portal-source"}
EXCLUDED_SUFFIXES = {".pyc", ".sqlite3", ".db", ".log", ".zip", ".sha256"}
EXCLUDED_RELATIVE_PATHS = {
    "docs/FINAL_RELEASE_CERTIFICATION.md", "docs/FOUR_DOMAIN_EXTENSION.md",
    "docs/FOUR_DOMAIN_SCORECARD.md", "docs/IMPLEMENTATION_STATUS.md",
    "docs/SCORECARD_56_DOMAINS.md", "docs/SECOND_PASS_RELEASE_AUDIT.md",
    "docs/STRICT_COMPLIANCE_AUDIT.md",
}
PRIVATE_KEY_SUFFIXES = {".pem", ".key", ".p12", ".pfx", ".jks"}
PRIVATE_KEY_NAMES = {"id_rsa", "id_ed25519"}


def include(path: Path) -> bool:
    rel = path.relative_to(ROOT)
    if rel.as_posix() in EXCLUDED_RELATIVE_PATHS:
        return False
    if any(part in EXCLUDED_PARTS for part in rel.parts) or path.suffix.lower() in EXCLUDED_SUFFIXES:
        return False
    if path.name == ".env" or path.name.lower() in PRIVATE_KEY_NAMES or path.suffix.lower() in PRIVATE_KEY_SUFFIXES:
        return False
    if "outputs" in rel.parts and path.name not in {"sbom.cdx.json", "RELEASE_MANIFEST.json"}:
        return False
    return True


def source_files():
    for current, directories, filenames in os.walk(ROOT):
        directories[:] = [name for name in directories if name not in EXCLUDED_PARTS]
        for filename in filenames:
            yield Path(current) / filename


def assert_no_private_keys() -> None:
    findings = []
    for path in source_files():
        rel = path.relative_to(ROOT)
        if any(part in EXCLUDED_PARTS for part in rel.parts):
            continue
        if path.name.lower() in PRIVATE_KEY_NAMES or path.suffix.lower() in PRIVATE_KEY_SUFFIXES:
            findings.append(rel.as_posix())
    if findings:
        raise SystemExit("Private signing/key artifacts must not be present in release source: " + ", ".join(findings))


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=DEFAULT_OUT)
    args = parser.parse_args()
    output = args.output if args.output.is_absolute() else ROOT / args.output
    output.parent.mkdir(parents=True, exist_ok=True)
    assert_no_private_keys()
    subprocess.run([sys.executable, str(ROOT / "scripts" / "generate_sbom.py")], check=True)
    subprocess.run([sys.executable, str(ROOT / "scripts" / "generate_release_manifest.py")], check=True)
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(source_files()):
            if path.is_file() and path != output and include(path):
                archive.write(path, path.relative_to(ROOT).as_posix())
    checksum = sha256(output)
    checksum_path = output.with_suffix(output.suffix + ".sha256")
    checksum_path.write_text(f"{checksum}  {output.name}\n", encoding="ascii")
    subprocess.run([
        sys.executable, str(ROOT / "scripts" / "generate_release_manifest.py"),
        "--release", str(output),
    ], check=True)
    subprocess.run([
        sys.executable, str(ROOT / "scripts" / "verify_release_package.py"),
        str(output), "--manifest", str(ROOT / "outputs" / "RELEASE_MANIFEST.json"),
        "--checksum", str(checksum_path),
    ], check=True)
    print(output)
    print(checksum_path)


if __name__ == "__main__":
    main()
