import uuid
from datetime import timedelta

from django.conf import settings
from django.db import models
from django.db.models import Q
from django.utils import timezone


class EventQuerySet(models.QuerySet):
    """Queries that enforce the public event-availability rules."""

    def publicly_available(self, now=None):
        """Return events that may safely be advertised to the public.

        The time predicates deliberately remain in the query even though due
        events are persisted as inactive by ``deactivate_due_events``.  This
        makes public visibility safe if the scheduled task is delayed.
        """
        return self.filter(Event.public_availability_filter(now))


class Event(models.Model):
    # Stop advertising an event shortly before it begins.  This gives clients
    # a clear cut-off for discovery and ticket sales while retaining the event
    # record for the host and administrators.
    DEACTIVATION_LEAD_TIME = timedelta(minutes=1)

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
    is_active = models.BooleanField(default=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    objects = EventQuerySet.as_manager()

    class Meta:
        ordering = ['-start_datetime']
        indexes = [
            models.Index(fields=['status', 'latitude', 'longitude'], name='event_nearby_idx'),
            models.Index(fields=['status', 'is_active', 'start_datetime'], name='event_active_list_idx'),
        ]
        constraints = [
            models.CheckConstraint(
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
        ]

    def __str__(self):
        return f"{self.title} ({self.start_datetime.date()})"

    @classmethod
    def public_availability_filter(cls, now=None):
        """Return the shared public-discovery condition for an event."""
        now = now or timezone.now()
        return Q(
            status='published',
            is_active=True,
            host__is_active=True,
            start_datetime__gt=now + cls.DEACTIVATION_LEAD_TIME,
            end_datetime__gt=now,
        )

    @classmethod
    def due_for_deactivation(cls, now=None):
        """Return the condition for events that must no longer be active."""
        now = now or timezone.now()
        return (
            Q(status__in=('cancelled', 'completed'))
            | Q(start_datetime__lte=now + cls.DEACTIVATION_LEAD_TIME)
            | Q(end_datetime__lte=now)
        )

    def should_be_inactive(self, now=None):
        """Whether this event's current state must disable public activity."""
        now = now or timezone.now()
        return (
            self.status in {'cancelled', 'completed'}
            or self.start_datetime <= now + self.DEACTIVATION_LEAD_TIME
            or self.end_datetime <= now
        )

    @classmethod
    def deactivate_due_events(cls, now=None):
        """Persistently deactivate due events and return the number changed.

        The update only targets active rows, so it is safe to invoke from a
        one-minute cron job and from request paths without repeated writes.
        """
        now = now or timezone.now()
        return (
            cls.objects.filter(is_active=True)
            .filter(cls.due_for_deactivation(now))
            .update(is_active=False)
        )

    def save(self, *args, **kwargs):
        """Keep terminal or due events inactive, including admin/ORM edits."""
        if self.is_active and self.should_be_inactive():
            self.is_active = False
            if kwargs.get('update_fields') is not None:
                kwargs['update_fields'] = set(kwargs['update_fields']) | {
                    'is_active',
                    'updated_at',
                }
        super().save(*args, **kwargs)

    @property
    def is_sold_out(self):
        from django.db.models import F
        ticket_types = self.ticket_types.all()
        if not ticket_types.exists():
            return False
        return not ticket_types.filter(quantity_sold__lt=F('quantity_total')).exists()
