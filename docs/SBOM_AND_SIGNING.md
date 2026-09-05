# SBOM, Provenance, and Signing

## Generate release evidence

```bash
python scripts/generate_sbom.py
python scripts/generate_release_manifest.py
python scripts/build_release_package.py
```

The build creates:

- `outputs/sbom.cdx.json`: CycloneDX 1.5 runtime dependency closure and static-asset inventory, with direct requirements identified and `requirements.txt` hashed. Test and audit-only packages are excluded.
- `outputs/RELEASE_MANIFEST.json`: SHA-256 payload inventory and final archive metadata.
- `outputs/aurafoods_unified_release.zip`: deployable source artifact.
- `outputs/aurafoods_unified_release.zip.sha256`: detached final archive checksum.

The package contains the SBOM and pre-build payload manifest. After packaging, the detached manifest is updated with the final archive hash. This avoids the impossible self-reference of embedding an archive's final digest inside that same archive.

## Verify

```bash
python -c "import hashlib,pathlib; p=pathlib.Path('outputs/aurafoods_unified_release.zip'); print(hashlib.sha256(p.read_bytes()).hexdigest())"
```

Compare the result with the `.sha256` file and the detached release manifest.

## Signing readiness

Use Sigstore Cosign for keyless CI signing, or a hardware-backed private key for controlled releases:

```bash
cosign sign-blob --yes --bundle outputs/aurafoods_unified_release.zip.sigstore.json outputs/aurafoods_unified_release.zip
cosign verify-blob --bundle outputs/aurafoods_unified_release.zip.sigstore.json --certificate-identity YOUR_CI_IDENTITY --certificate-oidc-issuer YOUR_OIDC_ISSUER outputs/aurafoods_unified_release.zip
```

Private keys belong in a cloud KMS, HSM, or CI secret store. Never add them to this repository. This release is checksum-ready but must not be described as signed until a verifiable signature bundle exists.
The package build fails if a `.pem`, `.key`, `.p12`, `.pfx`, `.jks`, `id_rsa`, or `id_ed25519` file is found outside excluded runtime directories.
