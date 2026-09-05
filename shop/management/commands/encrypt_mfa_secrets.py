from django.core.management.base import BaseCommand

from shop.models import StaffMFADevice
from shop.services.mfa_crypto import encrypt_totp_secret, is_encrypted_secret


class Command(BaseCommand):
    help = "Encrypt legacy plaintext staff MFA secrets using MFA_SECRET_ENCRYPTION_KEY."

    def handle(self, *args, **options):
        updated = 0
        for device in StaffMFADevice.objects.all():
            if is_encrypted_secret(device.secret):
                continue
            device.secret = encrypt_totp_secret(device.secret)
            device.save(update_fields=["secret"])
            updated += 1
        self.stdout.write(self.style.SUCCESS(f"Encrypted {updated} legacy MFA secret(s)."))
