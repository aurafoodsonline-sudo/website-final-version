from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse


class OperationsConsoleTests(TestCase):
    def test_console_requires_login(self):
        response = self.client.get(reverse("frontend:operations-console"))
        self.assertEqual(response.status_code, 302)
        self.assertIn("/admin/login/", response["Location"])

    def test_console_renders_for_authenticated_user(self):
        user = get_user_model().objects.create_user(username="ops", password="pw", is_staff=True)
        self.client.force_login(user)
        response = self.client.get(reverse("frontend:operations-console"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "AuraFoods Operations")
        self.assertContains(response, "Direct Purchase")
        self.assertNotContains(response, "Create GRN</button>", html=False)

    def test_console_shows_core_workflows_for_privileged_user(self):
        user = get_user_model().objects.create_superuser(username="admin", password="pw", email="admin@example.com")
        self.client.force_login(user)
        response = self.client.get(reverse("frontend:operations-console"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Packing wastage units")
        self.assertContains(response, "FEFO Dispatch")
        self.assertContains(response, "Create GRN")
        self.assertContains(response, "Post Payment")
