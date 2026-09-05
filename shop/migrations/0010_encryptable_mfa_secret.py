from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("shop", "0009_policypage_staffmfadevice_adminactivitylog_severity_and_more"),
    ]

    operations = [
        migrations.AlterField(
            model_name="staffmfadevice",
            name="secret",
            field=models.CharField(max_length=255),
        ),
    ]
