from django.db import transaction
from rest_framework import serializers

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


class TicketSerializer(serializers.ModelSerializer):
    event_title = serializers.CharField(
        source='ticket_type.event.title',
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
    ticket_type = serializers.UUIDField()
    quantity = serializers.IntegerField(min_value=1)

    def validate_ticket_type(self, value):
        if not TicketType.objects.filter(id=value).exists():
            raise serializers.ValidationError("Ticket type not found.")
        return value

    def validate(self, attrs):
        # Fast, friendly upfront check. Not the authoritative one — see create().
        ticket_type = TicketType.objects.get(id=attrs['ticket_type'])
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
        ticket_type = TicketType.objects.select_for_update().get(id=validated_data['ticket_type'])
        quantity = validated_data['quantity']

        if ticket_type.quantity_remaining < quantity:
            raise serializers.ValidationError(
                {"quantity": f"Only {ticket_type.quantity_remaining} ticket(s) left for '{ticket_type.name}'."}
            )

        user = self.context['request'].user
        tickets = [Ticket.objects.create(ticket_type=ticket_type, user=user) for _ in range(quantity)]

        ticket_type.quantity_sold += quantity
        ticket_type.save(update_fields=['quantity_sold'])

        return tickets