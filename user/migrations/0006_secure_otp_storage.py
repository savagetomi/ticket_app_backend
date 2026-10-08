from django.db import migrations, models


def invalidate_legacy_otps(apps, schema_editor):
    """Plaintext OTPs cannot be safely migrated to hashes, so expire them."""
    apps.get_model('user', 'OTP').objects.all().delete()


class Migration(migrations.Migration):

    dependencies = [
        ('user', '0005_customuser_roles'),
    ]

    operations = [
        migrations.RunPython(invalidate_legacy_otps, migrations.RunPython.noop),
        migrations.RenameField(
            model_name='otp',
            old_name='otp_code',
            new_name='otp_code_hash',
        ),
        migrations.AlterField(
            model_name='otp',
            name='otp_code_hash',
            field=models.CharField(blank=True, max_length=128),
        ),
        migrations.AddField(
            model_name='otp',
            name='failed_attempts',
            field=models.PositiveSmallIntegerField(default=0),
        ),
        migrations.AddField(
            model_name='otp',
            name='locked_until',
            field=models.DateTimeField(blank=True, null=True),
        ),
    ]
