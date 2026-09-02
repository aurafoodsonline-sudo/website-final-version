import base64
import hmac
import secrets
import struct
import time
from hashlib import sha1

from django.conf import settings
from django.utils import timezone

from shop.models import StaffMFADevice
from shop.services.mfa_crypto import decrypt_totp_secret, is_encrypted_secret


def generate_totp_secret():
    return base64.b32encode(secrets.token_bytes(20)).decode("ascii").rstrip("=")


def _normalize_secret(secret):
    padding = "=" * ((8 - len(secret) % 8) % 8)
    return base64.b32decode((secret + padding).upper())


def totp_code(secret, timestamp=None, step=30, digits=6):
    counter = int((timestamp or time.time()) // step)
    digest = hmac.new(_normalize_secret(secret), struct.pack(">Q", counter), sha1).digest()
    offset = digest[-1] & 0x0F
    value = struct.unpack(">I", digest[offset : offset + 4])[0] & 0x7FFFFFFF
    return str(value % (10**digits)).zfill(digits)


def verify_totp(secret, token, timestamp=None, window=1):
    candidate = "".join(ch for ch in str(token or "") if ch.isdigit())
    if len(candidate) != 6:
        return False
    now = timestamp or time.time()
    for drift in range(-window, window + 1):
        if hmac.compare_digest(totp_code(secret, now + (drift * 30)), candidate):
            return True
    return False


def staff_mfa_required(user):
    return bool(
        user
        and user.is_staff
        and getattr(settings, "STAFF_MFA_REQUIRED", False)
    )


def confirmed_device_for(user):
    if not user or not user.is_authenticated:
        return None
    return StaffMFADevice.objects.filter(user=user, confirmed=True).order_by("-created_at").first()


def verify_staff_token(user, token):
    device = confirmed_device_for(user)
    if not device:
        return False
    secret = decrypt_totp_secret(device.secret)
    if not verify_totp(secret, token):
        return False
    device.last_used_at = timezone.now()
    if not is_encrypted_secret(device.secret):
        device.secret = secret
        device.save(update_fields=["secret", "last_used_at"])
    else:
        device.save(update_fields=["last_used_at"])
    return True
