import os

from django.contrib.auth import get_user_model
from django.db import DatabaseError


def ensure_admin_user():
    User = get_user_model()
    try:
        if User.objects.filter(is_superuser=True).exists():
            return None
        if User.objects.filter(username="admin").exists():
            return None

        password = os.environ.get("AURAFOODS_ADMIN_PASSWORD")
        if password:
            user = User.objects.create_superuser("admin", "admin@aurafoods.pk", password)
            return user

        user = User.objects.create_user(
            "admin",
            "admin@aurafoods.pk",
            password=None,
            is_staff=True,
            is_superuser=True,
        )
        user.set_unusable_password()
        user.save(update_fields=["password"])
        return user
    except DatabaseError:
        # Database not migrated or not reachable yet (for example the URLconf is
        # imported by a build step, or by `migrate` before the tables exist).
        # Never let bootstrap raise out of module import: that would turn every
        # page on the public site into a 500.
        return None
