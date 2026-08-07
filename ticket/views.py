from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import serializers as drf_serializers, status
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from drf_spectacular.utils import extend_schema, inline_serializer, OpenApiResponse

from event.models import Event
from user.permissions import IsHost  # adjust to match your actual app name
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
        description="Returns all ticket types (e.g. VIP, Regular) defined for the given event. Public.",
        responses={200: TicketTypeSerializer(many=True)}
    )
    def get(self, request, event_id):
        get_object_or_404(Event, id=event_id)
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
        event = get_object_or_404(Event, id=event_id)
        if event.host_id != request.user.id:
            return Response(
                {'success': False, 'message': 'You can only add ticket types to your own events.'},
                status=status.HTTP_403_FORBIDDEN
            )

        serializer = TicketTypeSerializer(data=request.data)
        if serializer.is_valid():
            ticket_type = serializer.save(event=event)
            return Response(
                {
                    'success': True,
                    'message': 'Ticket type created successfully',
                    'ticket_type': TicketTypeSerializer(ticket_type).data,
                },
                status=status.HTTP_201_CREATED
            )
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


class TicketPurchaseView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        tags=['Tickets'],
        summary="Purchase tickets",
        description="Buys `quantity` tickets of the given ticket type for the authenticated user. Fails if not enough tickets remain. NOTE: no payment gateway is wired in yet — this issues tickets immediately without charging anything.",
        request=PurchaseTicketSerializer,
        responses={
            201: OpenApiResponse(description="Tickets purchased"),
            400: OpenApiResponse(description="Not enough tickets remaining, or invalid ticket type"),
        }
    )
    def post(self, request):
        serializer = PurchaseTicketSerializer(data=request.data, context={'request': request})
        if serializer.is_valid():
            tickets = serializer.save()
            return Response(
                {
                    'success': True,
                    'message': f'{len(tickets)} ticket(s) purchased successfully',
                    'tickets': TicketSerializer(tickets, many=True).data,
                },
                status=status.HTTP_201_CREATED
            )
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


class MyTicketsView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        tags=['Tickets'],
        summary="List my tickets",
        description="Returns all tickets purchased by the authenticated user.",
        responses={200: TicketSerializer(many=True)}
    )
    def get(self, request):
        tickets = Ticket.objects.filter(user=request.user)
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
                    'ticket': TicketSerializer(),
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

        try:
            ticket = Ticket.objects.select_related('ticket_type__event').get(ticket_code=ticket_code)
        except Ticket.DoesNotExist:
            return Response({'success': False, 'message': 'Ticket not found.'}, status=status.HTTP_404_NOT_FOUND)

        if ticket.ticket_type.event.host_id != request.user.id:
            return Response(
                {'success': False, 'message': "This ticket belongs to another host's event."},
                status=status.HTTP_403_FORBIDDEN
            )

        if ticket.status == 'used':
            return Response({'success': False, 'message': 'This ticket has already been checked in.'}, status=status.HTTP_400_BAD_REQUEST)

        if ticket.status == 'cancelled':
            return Response({'success': False, 'message': 'This ticket has been cancelled.'}, status=status.HTTP_400_BAD_REQUEST)

        ticket.status = 'used'
        ticket.checked_in_at = timezone.now()
        ticket.save(update_fields=['status', 'checked_in_at'])

        return Response(
            {'success': True, 'message': 'Ticket checked in successfully.', 'ticket': TicketSerializer(ticket).data},
            status=status.HTTP_200_OK
        )