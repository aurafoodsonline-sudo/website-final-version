import os

from django.contrib.auth import get_user_model
from django.test import TestCase

from shop.admin_bootstrap import ensure_admin_user


class EnsureAdminUserTests(TestCase):
    def test_creates_superuser_from_environment_password(self):
        User = get_user_model()
        User.objects.all().delete()
        os.environ["AURAFOODS_ADMIN_PASSWORD"] = "TestPass123!"

        try:
            ensure_admin_user()
        finally:
            os.environ.pop("AURAFOODS_ADMIN_PASSWORD", None)

        user = User.objects.get(username="admin")
        self.assertTrue(user.is_superuser)
        self.assertTrue(user.is_staff)
        self.assertTrue(user.check_password("TestPass123!"))
