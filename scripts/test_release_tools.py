import hashlib
import json
import zipfile

import pytest

from scripts import build_release_package
from scripts.verify_release_package import verify


def _archive(path, extra_name=None):
    payload = {
        name: b"test"
        for name in (
            ".env.example", "Dockerfile", "README.md", "docker-compose.yml", "manage.py",
            "requirements.txt", "docs/UNIFIED_DEPLOYMENT_RUNBOOK.md",
            "erp/migrations/0001_initial.py", "shop/migrations/0001_initial.py",
            "sales/migrations/0001_initial.py", "crm/migrations/0001_initial.py",
            "outputs/sbom.cdx.json",
        )
    }
    if extra_name:
        payload[extra_name] = b"unsafe"
    manifest = {
        "payload": {
            "file_count": len(payload),
            "files": [
                {"path": name, "size": len(data), "sha256": hashlib.sha256(data).hexdigest()}
                for name, data in payload.items()
            ],
        }
    }
    with zipfile.ZipFile(path, "w") as archive:
        for name, data in payload.items():
            archive.writestr(name, data)
        archive.writestr("outputs/RELEASE_MANIFEST.json", json.dumps(manifest))


def test_release_verifier_accepts_matching_payload(tmp_path):
    archive = tmp_path / "release.zip"
    _archive(archive)
    verify(archive)


def test_release_verifier_rejects_path_traversal(tmp_path):
    archive = tmp_path / "release.zip"
    _archive(archive, "../escape.txt")
    with pytest.raises(SystemExit, match="Unsafe archive path"):
        verify(archive)


def test_release_builder_rejects_private_keys(monkeypatch, tmp_path):
    key = tmp_path / "deployment.key"
    key.write_text("not-a-real-key", encoding="ascii")
    monkeypatch.setattr(build_release_package, "ROOT", tmp_path)
    monkeypatch.setattr(build_release_package, "source_files", lambda: iter([key]))
    with pytest.raises(SystemExit, match="Private signing/key artifacts"):
        build_release_package.assert_no_private_keys()
