from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('event', '0001_initial'),
    ]

    operations = [
        migrations.AddConstraint(
            model_name='event',
            constraint=models.CheckConstraint(
                condition=(
                    models.Q(latitude__isnull=True, longitude__isnull=True)
                    | models.Q(
                        latitude__isnull=False,
                        longitude__isnull=False,
                        latitude__gte=-90,
                        latitude__lte=90,
                        longitude__gte=-180,
                        longitude__lte=180,
                    )
                ),
                name='event_valid_coordinates',
            ),
        ),
        migrations.AddIndex(
            model_name='event',
            index=models.Index(fields=['status', 'latitude', 'longitude'], name='event_nearby_idx'),
        ),
    ]
