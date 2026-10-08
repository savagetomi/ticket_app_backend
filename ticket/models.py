import random
import secrets
import string
import uuid

from django.conf import settings
from django.db import models

from event.models import Event

def generate_ticket_code():
    """TKT-XXXXXXXX — 8 chars from a 32-char alphabet (O/0/I/1 excluded for
    readability). secrets, not random, because this code doubles as an
    entry credential — it needs to be unguessable, not just unique."""
    alphabet = string.ascii_uppercase + string.digits
    alphabet = alphabet.translate(str.maketrans('', '', 'O0I1'))
    suffix = ''.join(secrets.choice(alphabet) for _ in range(8))
    return f'TKT-{suffix}'


class TicketType(models.Model):
    id = models.UUIDField(default=uuid.uuid4, unique=True, editable=False, primary_key=True)
    event = models.ForeignKey(Event, on_delete=models.CASCADE, related_name='ticket_types')
    name = models.CharField(max_length=100)  # e.g. "VIP", "Regular", "Early Bird"
    description = models.CharField(max_length=255, blank=True)
    price = models.DecimalField(max_digits=10, decimal_places=2)
    quantity_total = models.PositiveIntegerField()
    quantity_sold = models.PositiveIntegerField(default=0)
    sales_start = models.DateTimeField(blank=True, null=True)
    sales_end = models.DateTimeField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['price']

    def __str__(self):
        return f"{self.name} - {self.event.title}"

    @property
    def quantity_remaining(self):
        return self.quantity_total - self.quantity_sold

    @property
    def is_sold_out(self):
        return self.quantity_remaining <= 0


class Ticket(models.Model):
    STATUS_CHOICES = (
        ('valid', 'Valid'),
        ('used', 'Used'),
        ('cancelled', 'Cancelled'),
    )

    id = models.UUIDField(default=uuid.uuid4, unique=True, editable=False, primary_key=True)
    ticket_type = models.ForeignKey(TicketType, on_delete=models.CASCADE, related_name='tickets')
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='tickets')
    ticket_code = models.CharField(max_length=12, unique=True, editable=False)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='valid')
    purchased_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    checked_in_at = models.DateTimeField(blank=True, null=True)

    class Meta:
        ordering = ['-purchased_at']

    def __str__(self):
        return f"{self.ticket_code} - {self.ticket_type.name}"

    def save(self, *args, **kwargs):
        if not self.ticket_code:
            code = generate_ticket_code()
            # Collision odds are ~1 in 10^12 (32^8) — this loop is a formality,
            # the DB-level unique constraint on ticket_code is the real backstop
            while Ticket.objects.filter(ticket_code=code).exists():
                code = generate_ticket_code()
            self.ticket_code = code
        super().save(*args, **kwargs)
