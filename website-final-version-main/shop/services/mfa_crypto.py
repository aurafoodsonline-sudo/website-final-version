from cryptography.fernet import Fernet, InvalidToken
from django.conf import settings
from django.core.exceptions import ImproperlyConfigured, ValidationError


FERNET_PREFIX = "fernet:"


def mfa_encryption_key():
    key = getattr(settings, "MFA_SECRET_ENCRYPTION_KEY", "")
    if key:
        return key
    if getattr(settings, "DEBUG", False):
        return settings.MFA_SECRET_ENCRYPTION_DEV_KEY
    raise ImproperlyConfigured("MFA_SECRET_ENCRYPTION_KEY is required to use staff MFA secrets.")


def mfa_cipher():
    try:
        return Fernet(mfa_encryption_key().encode("ascii"))
    except ValueError as exc:
        raise ImproperlyConfigured("MFA_SECRET_ENCRYPTION_KEY must be a valid Fernet key.") from exc


def is_encrypted_secret(value):
    return bool(value and str(value).startswith(FERNET_PREFIX))


def encrypt_totp_secret(secret):
    if not secret:
        return secret
    if is_encrypted_secret(secret):
        return secret
    token = mfa_cipher().encrypt(str(secret).encode("ascii")).decode("ascii")
    return f"{FERNET_PREFIX}{token}"


def decrypt_totp_secret(stored_secret):
    if not stored_secret:
        return ""
    if not is_encrypted_secret(stored_secret):
        return stored_secret
    token = stored_secret[len(FERNET_PREFIX) :].encode("ascii")
    try:
        return mfa_cipher().decrypt(token).decode("ascii")
    except InvalidToken as exc:
        raise ValidationError("Stored MFA secret cannot be decrypted with the configured key.") from exc
