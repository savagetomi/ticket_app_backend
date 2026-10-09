from datetime import timedelta

from django.contrib.auth import get_user_model
from django.db import transaction
from django.utils import timezone
from rest_framework import serializers

from event.models import Event
from .models import Ticket, TicketType


class TicketTypeSerializer(serializers.ModelSerializer):
    quantity_remaining = serializers.IntegerField(read_only=True)
    is_sold_out = serializers.BooleanField(read_only=True)

    class Meta:
        model = TicketType
        fields = [
            'id', 'event', 'name', 'description', 'price',
            'quantity_total', 'quantity_sold', 'quantity_remaining',
            'is_sold_out', 'sales_start', 'sales_end', 'created_at', 'updated_at',
        ]
        read_only_fields = ['id', 'event', 'quantity_sold', 'created_at', 'updated_at']

    def validate(self, attrs):
        sales_start = attrs.get('sales_start', getattr(self.instance, 'sales_start', None))
        sales_end = attrs.get('sales_end', getattr(self.instance, 'sales_end', None))
        if sales_start and sales_end and sales_end <= sales_start:
            raise serializers.ValidationError(
                {'sales_end': 'Sales must end after they start.'}
            )
        return attrs


class TicketSerializer(serializers.ModelSerializer):
    event_title = serializers.CharField(
        source='ticket_type.event.title',
        read_only=True
    )
    event_description = serializers.CharField(
        source='ticket_type.event.description',
        read_only=True
    )

    event_start_datetime = serializers.DateTimeField(
        source='ticket_type.event.start_datetime',
        read_only=True
    )

    event_end_datetime = serializers.DateTimeField(
        source='ticket_type.event.end_datetime',
        read_only=True
    )

    event_venue_name = serializers.CharField(
        source='ticket_type.event.venue_name',
        read_only=True
    )

    event_address = serializers.CharField(
        source='ticket_type.event.address',
        read_only=True
    )

    event_city = serializers.CharField(
        source='ticket_type.event.city',
        read_only=True
    )

    event_state = serializers.CharField(
        source='ticket_type.event.state',
        read_only=True
    )

    event_country = serializers.CharField(
        source='ticket_type.event.country',
        read_only=True
    )

    ticket_type_name = serializers.CharField(
        source='ticket_type.name',
        read_only=True
    )

    price = serializers.DecimalField(
        source='ticket_type.price',
        max_digits=10,
        decimal_places=2,
        read_only=True
    )

    class Meta:
        model = Ticket
        fields = [
            'id',
            'ticket_code',

            'ticket_type',
            'ticket_type_name',

            'event_title',
            'event_description',
            'event_start_datetime',
            'event_end_datetime',
            'event_venue_name',
            'event_address',
            'event_city',
            'event_state',
            'event_country',

            'price',

            'user',
            'status',
            'purchased_at',
            'updated_at',
            'checked_in_at',
        ]

        read_only_fields = fields


class PurchaseTicketSerializer(serializers.Serializer):
    MAX_TICKETS_PER_ORDER = 10
    SALE_CLOSE_BUFFER = timedelta(minutes=1)

    ticket_type = serializers.UUIDField()
    quantity = serializers.IntegerField(min_value=1, max_value=MAX_TICKETS_PER_ORDER)

    @classmethod
    def refresh_event_lifecycle(cls, now=None):
        """Persist time-based event deactivations before exposing ticket sales."""
        now = now or timezone.now()
        Event.deactivate_due_events(now=now)
        return now

    @classmethod
    def event_is_available_for_sale(cls, event, now):
        """Return whether an event may still expose or sell ticket types."""
        return (
            event.status == 'published'
            and event.is_active
            and event.host.is_active
            and event.start_datetime > now + cls.SALE_CLOSE_BUFFER
            and event.end_datetime > now
        )

    @classmethod
    def event_allows_ticket_type_configuration(cls, event, now):
        """Allow a host to prepare a future draft without opening sales."""
        return (
            event.status not in {'cancelled', 'completed'}
            and event.is_active
            and event.host.is_active
            and event.start_datetime > now + cls.SALE_CLOSE_BUFFER
            and event.end_datetime > now
        )

    @classmethod
    def _validate_sale_is_open(cls, ticket_type, now):
        event = ticket_type.event

        if not cls.event_is_available_for_sale(event, now):
            raise serializers.ValidationError(
                {'ticket_type': 'Tickets are not available for this event.'}
            )
        if ticket_type.sales_start and now < ticket_type.sales_start:
            raise serializers.ValidationError(
                {'ticket_type': 'Ticket sales have not started yet.'}
            )
        if ticket_type.sales_end and now > ticket_type.sales_end:
            raise serializers.ValidationError(
                {'ticket_type': 'Ticket sales have ended.'}
            )

    def validate_ticket_type(self, value):
        if not TicketType.objects.filter(id=value).exists():
            raise serializers.ValidationError("Ticket type not found.")
        return value

    def validate(self, attrs):
        # Fast, friendly upfront check. Not the authoritative one — see create().
        now = self.refresh_event_lifecycle()
        ticket_type = TicketType.objects.select_related('event__host').get(
            id=attrs['ticket_type']
        )
        self._validate_sale_is_open(ticket_type, now)
        if ticket_type.quantity_remaining < attrs['quantity']:
            raise serializers.ValidationError(
                {"quantity": f"Only {ticket_type.quantity_remaining} ticket(s) left for '{ticket_type.name}'."}
            )
        return attrs

    @transaction.atomic
    def create(self, validated_data):
        # select_for_update() locks this row until the transaction commits, so if
        # two people try to buy the last ticket at the same instant, the second
        # request blocks until the first finishes, re-reads the now-updated
        # quantity_sold, and correctly fails instead of both succeeding
        # (which would oversell the event). Note: this only actually locks on
        # Postgres/MySQL — it's a silent no-op on SQLite.
        now = self.refresh_event_lifecycle()
        ticket_type = TicketType.objects.select_for_update().get(
            id=validated_data['ticket_type']
        )
        event = Event.objects.select_for_update().select_related('host').get(
            pk=ticket_type.event_id
        )
        # A user account may be deactivated concurrently with a purchase.
        # Lock and re-read it before the authoritative availability check.
        host = get_user_model().objects.select_for_update().get(pk=event.host_id)
        event.host = host
        if event.is_active and event.should_be_inactive(now):
            event.is_active = False
            event.save(update_fields=['is_active', 'updated_at'])
        ticket_type.event = event
        quantity = validated_data['quantity']

        # Re-check after locking so a sale closing or event state change cannot
        # be bypassed between serializer validation and ticket creation.
        self._validate_sale_is_open(ticket_type, now)

        if ticket_type.quantity_remaining < quantity:
            raise serializers.ValidationError(
                {"quantity": f"Only {ticket_type.quantity_remaining} ticket(s) left for '{ticket_type.name}'."}
            )

        user = self.context['request'].user
        tickets = [Ticket.objects.create(ticket_type=ticket_type, user=user) for _ in range(quantity)]

        ticket_type.quantity_sold += quantity
        ticket_type.save(update_fields=['quantity_sold'])

        return tickets
