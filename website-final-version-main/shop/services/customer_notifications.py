from django.conf import settings
from django.core.mail import send_mail


def _absolute_url(request, path):
    if request is not None:
        return request.build_absolute_uri(path)
    base = "https://aurafoods.pk"
    return f"{base}{path}"


def send_customer_verification_email(user, token, request=None):
    if not user.email:
        return False
    link = _absolute_url(request, f"/account/verify-email/{token}/")
    return bool(
        send_mail(
            "Verify your Aura Foods email",
            (
                f"Hello {user.username},\n\n"
                "Please verify your Aura Foods customer account email using this link:\n"
                f"{link}\n\n"
                "If you did not create this account, you can ignore this message."
            ),
            settings.DEFAULT_FROM_EMAIL,
            [user.email],
            fail_silently=True,
        )
    )


def send_customer_password_reset_email(user, token, request=None):
    if not user.email:
        return False
    link = _absolute_url(request, f"/account/password-reset/{token}/")
    return bool(
        send_mail(
            "Reset your Aura Foods password",
            (
                f"Hello {user.username},\n\n"
                "A password reset was requested for your Aura Foods customer account.\n"
                f"Use this link to choose a new password: {link}\n\n"
                "If you did not request this, you can ignore this message."
            ),
            settings.DEFAULT_FROM_EMAIL,
            [user.email],
            fail_silently=True,
        )
    )
