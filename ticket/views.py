from django.db import transaction
from django.db.models import Q
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import serializers as drf_serializers, status
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView
from drf_spectacular.utils import extend_schema, inline_serializer, OpenApiResponse

from event.models import Event
from user.permissions import IsActiveAuthenticated, IsHost
from .models import Ticket, TicketType
from .serializers import PurchaseTicketSerializer, TicketSerializer, TicketTypeSerializer


class TicketTypeListCreateView(APIView):

    def get_permissions(self):
        if self.request.method == 'POST':
            return [IsHost()]
        return [AllowAny()]

    @extend_schema(
        tags=['Tickets'],
        summary="List ticket types for an event",
        description=(
            "Public for active, published events with more than one minute before "
            "they start; hosts may also list ticket types for their own non-public events."
        ),
        responses={200: TicketTypeSerializer(many=True)}
    )
    def get(self, request, event_id):
        now = PurchaseTicketSerializer.refresh_event_lifecycle()
        events = Event.objects.filter(id=event_id)
        if request.user.is_authenticated:
            events = events.filter(Event.public_availability_filter(now) | Q(host=request.user))
        else:
            events = events.filter(Event.public_availability_filter(now))
        get_object_or_404(events)
        ticket_types = TicketType.objects.filter(event_id=event_id)
        return Response(TicketTypeSerializer(ticket_types, many=True).data)

    @extend_schema(
        tags=['Tickets'],
        summary="Create a ticket type for an event",
        description="Defines a new ticket type (name, price, quantity) for an event. Restricted to the host who owns the event.",
        request=TicketTypeSerializer,
        responses={
            201: OpenApiResponse(description="Ticket type created"),
            400: OpenApiResponse(description="Validation errors"),
            403: OpenApiResponse(description="Not the event owner"),
        }
    )
    def post(self, request, event_id):
        now = PurchaseTicketSerializer.refresh_event_lifecycle()
        event = get_object_or_404(Event.objects.select_related('host'), id=event_id)
        if event.host_id != request.user.id:
            return Response(
                {'success': False, 'message': 'You can only add ticket types to your own events.'},
                status=status.HTTP_403_FORBIDDEN
            )
        if not PurchaseTicketSerializer.event_allows_ticket_type_configuration(event, now):
            return Response(
                {
                    'success': False,
                    'message': 'Ticket types are not available for this event.',
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        serializer = TicketTypeSerializer(data=request.data)
        if serializer.is_valid():
            ticket_type = serializer.save(event=event)
            return Response(
                {
                    'success': True,
                    'message': 'Ticket type created successfully',
                    'data': TicketTypeSerializer(ticket_type).data,
                },
                status=status.HTTP_201_CREATED
            )
        return Response({
            'success': False,
            'message': 'Invalid data provided',
            'errors': serializer.errors
        }, status=status.HTTP_400_BAD_REQUEST)


class TicketPurchaseView(APIView):
    permission_classes = [IsActiveAuthenticated]

    @extend_schema(
        tags=['Tickets'],
        summary="Purchase tickets",
        description="Buys `quantity` tickets of the given ticket type for the authenticated user. Sales close one minute before the event starts and are unavailable for inactive events or inactive hosts. Fails if not enough tickets remain. NOTE: no payment gateway is wired in yet — this issues tickets immediately without charging anything.",
        request=PurchaseTicketSerializer,
        responses={
            201: OpenApiResponse(description="Tickets purchased"),
            400: OpenApiResponse(description="Not enough tickets remaining, or invalid ticket type"),
        }
    )
    def post(self, request):
        serializer = PurchaseTicketSerializer(data=request.data, context={'request': request})
        if serializer.is_valid():
            try:
                tickets = serializer.save()
            except drf_serializers.ValidationError as exc:
                return Response(
                    {
                        'success': False,
                        'message': 'Tickets are no longer available for purchase.',
                        'errors': exc.detail,
                    },
                    status=status.HTTP_400_BAD_REQUEST,
                )
            return Response(
                {
                    'success': True,
                    'message': f'{len(tickets)} ticket(s) purchased successfully',
                    'data': TicketSerializer(tickets, many=True).data,
                },
                status=status.HTTP_201_CREATED
            )
        return Response({
            'success': False,
            'message': 'Invalid data provided',
            'errors': serializer.errors
        }, status=status.HTTP_400_BAD_REQUEST)


class MyTicketsView(APIView):
    permission_classes = [IsActiveAuthenticated]

    @extend_schema(
        tags=['Tickets'],
        summary="List my tickets",
        description="Returns all tickets purchased by the authenticated user.",
        responses={200: TicketSerializer(many=True)}
    )
    def get(self, request):
        tickets = Ticket.objects.filter(user=request.user).select_related('ticket_type__event')
        return Response(TicketSerializer(tickets, many=True).data)


class TicketCheckInView(APIView):
    permission_classes = [IsHost]

    @extend_schema(
        tags=['Tickets'],
        summary="Check in a ticket",
        description="Marks a ticket as used at the event entrance. Restricted to the host who owns the event the ticket belongs to.",
        request=inline_serializer(
            name='CheckInRequest',
            fields={'ticket_code': drf_serializers.CharField()}
        ),
        responses={
            200: inline_serializer(
                name='CheckInSuccessResponse',
                fields={
                    'success': drf_serializers.BooleanField(),
                    'message': drf_serializers.CharField(),
                    'data': TicketSerializer(),
                }
            ),
            400: inline_serializer(
                name='CheckInAlreadyUsedResponse',
                fields={'success': drf_serializers.BooleanField(), 'message': drf_serializers.CharField()}
            ),
            403: inline_serializer(
                name='CheckInForbiddenResponse',
                fields={'success': drf_serializers.BooleanField(), 'message': drf_serializers.CharField()}
            ),
            404: inline_serializer(
                name='CheckInNotFoundResponse',
                fields={'success': drf_serializers.BooleanField(), 'message': drf_serializers.CharField()}
            ),
        }
    )
    def post(self, request):
        ticket_code = request.data.get('ticket_code')

        if not ticket_code:
            return Response({'success': False, 'message': 'ticket_code is required.'}, status=status.HTTP_400_BAD_REQUEST)

        with transaction.atomic():
            try:
                # Lock the credential first so two gate devices cannot both
                # admit it. Filtering by host also avoids cross-event leakage.
                ticket = Ticket.objects.select_for_update().select_related('ticket_type').get(
                    ticket_code=ticket_code,
                    ticket_type__event__host=request.user,
                )
            except Ticket.DoesNotExist:
                return Response(
                    {'success': False, 'message': 'Ticket not available.'},
                    status=status.HTTP_404_NOT_FOUND,
                )

            # Lock the event too, so a cancellation or time-window update
            # cannot race the lifecycle check below.
            event = Event.objects.select_for_update().get(pk=ticket.ticket_type.event_id)
            now = timezone.now()
            if event.status != 'published':
                return Response(
                    {'success': False, 'message': 'Check-in is not available for this event.'},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            if now < event.start_datetime or now > event.end_datetime:
                return Response(
                    {'success': False, 'message': 'Check-in is not currently open for this event.'},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            if ticket.status != 'valid':
                message = (
                    'This ticket has already been checked in.'
                    if ticket.status == 'used'
                    else 'This ticket is no longer valid.'
                )
                return Response(
                    {'success': False, 'message': message},
                    status=status.HTTP_400_BAD_REQUEST,
                )

            ticket.status = 'used'
            ticket.checked_in_at = now
            ticket.save(update_fields=['status', 'checked_in_at'])

        return Response(
            {'success': True, 'message': 'Ticket checked in successfully.', 'data': TicketSerializer(ticket).data},
            status=status.HTTP_200_OK
        )
