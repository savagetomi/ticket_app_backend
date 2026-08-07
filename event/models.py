import uuid
from django.conf import settings
from django.db import models


class Event(models.Model):
    STATUS_CHOICES = (
        ('draft', 'Draft'),
        ('published', 'Published'),
        ('cancelled', 'Cancelled'),
        ('completed', 'Completed'),
    )

    CATEGORY_CHOICES = (
        ('party', 'Party'),
        ('concert', 'Concert'),
        ('festival', 'Festival'),
        ('sports', 'Sports'),
        ('other', 'Other'),
    )

    id = models.UUIDField(default=uuid.uuid4, unique=True, editable=False, primary_key=True)
    host = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='events')

    title = models.CharField(max_length=255)
    description = models.TextField(blank=True)
    category = models.CharField(max_length=20, choices=CATEGORY_CHOICES, default='other')
    cover_image = models.ImageField(upload_to='event_covers/', blank=True, null=True)

    venue_name = models.CharField(max_length=255)
    address = models.CharField(max_length=255)
    city = models.CharField(max_length=100)
    state = models.CharField(max_length=100, blank=True)
    country = models.CharField(max_length=100, default='Nigeria')
    latitude = models.FloatField(blank=True, null=True)
    longitude = models.FloatField(blank=True, null=True)

    start_datetime = models.DateTimeField()
    end_datetime = models.DateTimeField()

    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='draft')

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-start_datetime']

    def __str__(self):
        return f"{self.title} ({self.start_datetime.date()})"

    @property
    def is_sold_out(self):
        from django.db.models import F
        ticket_types = self.ticket_types.all()
        if not ticket_types.exists():
            return False
        return not ticket_types.filter(quantity_sold__lt=F('quantity_total')).exists()