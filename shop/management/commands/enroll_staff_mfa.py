from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django.utils.http import urlencode

from shop.models import AdminActivityLog, StaffMFADevice
from shop.services.mfa import generate_totp_secret


class Command(BaseCommand):
    help = "Create or rotate a confirmed TOTP MFA device for a staff user."

    def add_arguments(self, parser):
        parser.add_argument("username")
        parser.add_argument("--name", default="Authenticator app")
        parser.add_argument("--issuer", default="Aura Foods")
        parser.add_argument(
            "--rotate",
            action="store_true",
            help="Delete existing confirmed devices for this staff user before creating the new device.",
        )
        parser.add_argument(
            "--show-secret",
            action="store_true",
            help="Print sensitive one-time TOTP secret and provisioning URI. Use only in a trusted terminal.",
        )

    def handle(self, *args, **options):
        User = get_user_model()
        username = options["username"]
        user = User.objects.filter(username=username).first()
        if not user:
            raise CommandError(f"User '{username}' was not found.")
        if not user.is_staff:
            raise CommandError("MFA devices can only be enrolled for staff users.")

        if options["rotate"]:
            StaffMFADevice.objects.filter(user=user).delete()
            self.stdout.write(self.style.WARNING(f"Rotated existing MFA devices for {user.username}"))

        secret = generate_totp_secret()
        device = StaffMFADevice.objects.create(
            user=user,
            name=options["name"],
            secret=secret,
            confirmed=True,
        )
        AdminActivityLog.objects.create(
            actor=None,
            action="mfa_device_enrolled",
            model_name="StaffMFADevice",
            object_id=str(device.id),
            object_repr=user.username,
            new_value={"device_name": device.name, "rotated": bool(options["rotate"])},
            severity=AdminActivityLog.SEVERITY_CRITICAL if options["rotate"] else AdminActivityLog.SEVERITY_WARNING,
        )

        label = f"{options['issuer']}:{user.username}"
        query = urlencode({"secret": secret, "issuer": options["issuer"]})
        self.stdout.write(self.style.SUCCESS(f"Created MFA device {device.id} for {user.username}"))
        if options["show_secret"]:
            self.stdout.write(
                self.style.WARNING(
                    "Sensitive one-time enrollment material follows. Do not paste it into tickets, chat, logs, or source files."
                )
            )
            self.stdout.write(f"Secret: {secret}")
            self.stdout.write(f"Provisioning URI: otpauth://totp/{label}?{query}")
        else:
            self.stdout.write("Secret: [redacted]")
            self.stdout.write("Provisioning URI: [redacted]")
            self.stdout.write("Re-run with --show-secret only from a trusted terminal if manual enrollment is required.")
