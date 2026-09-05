from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ("shop", "0010_encryptable_mfa_secret"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.AddField(
            model_name="order",
            name="customer_user",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="customer_orders",
                to=settings.AUTH_USER_MODEL,
            ),
        ),
        migrations.AddField(
            model_name="order",
            name="email",
            field=models.EmailField(blank=True, default="", max_length=254),
        ),
        migrations.CreateModel(
            name="CustomerAddress",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("full_name", models.CharField(max_length=200)),
                ("phone", models.CharField(max_length=50)),
                ("city", models.CharField(max_length=100)),
                ("address", models.TextField()),
                ("is_default", models.BooleanField(default=False)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                (
                    "user",
                    models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="saved_addresses", to=settings.AUTH_USER_MODEL),
                ),
            ],
            options={
                "db_table": "customer_addresses",
                "ordering": ["-is_default", "-created_at"],
            },
        ),
        migrations.AddIndex(
            model_name="order",
            index=models.Index(fields=["customer_user", "created_at"], name="orders_custome_59121c_idx"),
        ),
        migrations.AddIndex(
            model_name="customeraddress",
            index=models.Index(fields=["user", "is_default"], name="customer_ad_user_id_37500b_idx"),
        ),
    ]
