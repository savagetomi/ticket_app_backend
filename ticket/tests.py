from datetime import timedelta
from types import SimpleNamespace

from django.test import TestCase
from django.utils import timezone
from rest_framework import serializers as drf_serializers
from rest_framework.test import APIRequestFactory, force_authenticate

from event.models import Event
from event.views import EventDetailView
from user.models import CustomUser

from .models import Ticket, TicketType
from .serializers import PurchaseTicketSerializer, TicketTypeSerializer
from .views import TicketCheckInView, TicketTypeListCreateView


class TicketIntegrityTests(TestCase):
    def setUp(self):
        self.host = CustomUser.objects.create_user(
            username='ticket-host',
            email_address='host@example.com',
            first_name='Ticket',
            last_name='Host',
            phone_number='08000000001',
            password='SafePassword123!',
            roles='host',
        )
        self.buyer = CustomUser.objects.create_user(
            username='ticket-buyer',
            email_address='buyer@example.com',
            first_name='Ticket',
            last_name='Buyer',
            phone_number='08000000002',
            password='SafePassword123!',
        )
        now = timezone.now()
        self.event = Event.objects.create(
            host=self.host,
            title='Test Event',
            venue_name='Test Venue',
            address='1 Test Street',
            city='Lagos',
            start_datetime=now + timedelta(hours=2),
            end_datetime=now + timedelta(hours=3),
            status='published',
        )
        self.ticket_type = TicketType.objects.create(
            event=self.event,
            name='Regular',
            price='1000.00',
            quantity_total=10,
            sales_start=now - timedelta(hours=2),
            sales_end=now + timedelta(hours=2),
        )

    def _purchase_serializer(self, quantity=1):
        return PurchaseTicketSerializer(
            data={'ticket_type': str(self.ticket_type.id), 'quantity': quantity},
            context={'request': SimpleNamespace(user=self.buyer)},
        )

    def _make_event_live(self):
        now = timezone.now()
        self.event.start_datetime = now - timedelta(minutes=30)
        self.event.end_datetime = now + timedelta(hours=1)
        # Discovery and sales deactivate at the start cutoff, but a host must
        # still be able to admit valid holders during the actual event window.
        self.event.is_active = False
        self.event.save(update_fields=['start_datetime', 'end_datetime', 'is_active'])

    def test_purchase_requires_published_event_and_open_sale(self):
        self.event.status = 'cancelled'
        self.event.save(update_fields=['status'])

        serializer = self._purchase_serializer()

        self.assertFalse(serializer.is_valid())

    def test_sale_end_is_enforced(self):
        self.ticket_type.sales_end = timezone.now() - timedelta(seconds=1)
        self.ticket_type.save(update_fields=['sales_end'])

        serializer = self._purchase_serializer()

        self.assertFalse(serializer.is_valid())

    def test_purchase_requires_an_active_event(self):
        self.event.is_active = False
        self.event.save(update_fields=['is_active'])

        serializer = self._purchase_serializer()

        self.assertFalse(serializer.is_valid())
        self.assertIn('ticket_type', serializer.errors)

    def test_purchase_rejects_an_event_starting_within_one_minute(self):
        now = timezone.now()
        self.event.start_datetime = now + timedelta(seconds=30)
        self.event.end_datetime = now + timedelta(hours=1)
        self.event.is_active = True
        self.event.save(
            update_fields=['start_datetime', 'end_datetime', 'is_active']
        )

        serializer = self._purchase_serializer()

        self.assertFalse(serializer.is_valid())
        self.event.refresh_from_db()
        self.assertFalse(self.event.is_active)

    def test_purchase_requires_an_active_host(self):
        self.host.is_active = False
        self.host.save(update_fields=['is_active'])

        serializer = self._purchase_serializer()

        self.assertFalse(serializer.is_valid())
        self.assertIn('ticket_type', serializer.errors)

    def test_purchase_rechecks_event_availability_after_validation(self):
        serializer = self._purchase_serializer()
        self.assertTrue(serializer.is_valid(), serializer.errors)

        self.event.is_active = False
        self.event.save(update_fields=['is_active'])

        with self.assertRaises(drf_serializers.ValidationError):
            serializer.save()
        self.assertEqual(Ticket.objects.count(), 0)

    def test_purchase_quantity_is_capped(self):
        serializer = self._purchase_serializer(
            quantity=PurchaseTicketSerializer.MAX_TICKETS_PER_ORDER + 1
        )

        self.assertFalse(serializer.is_valid())
        self.assertIn('quantity', serializer.errors)

    def test_ticket_sale_window_must_be_ordered(self):
        serializer = TicketTypeSerializer(
            self.ticket_type,
            data={
                'sales_start': timezone.now() + timedelta(hours=2),
                'sales_end': timezone.now() + timedelta(hours=1),
            },
            partial=True,
        )

        self.assertFalse(serializer.is_valid())
        self.assertIn('sales_end', serializer.errors)

    def test_draft_ticket_types_are_hidden_from_public(self):
        self.event.status = 'draft'
        self.event.save(update_fields=['status'])
        factory = APIRequestFactory()

        anonymous_response = TicketTypeListCreateView.as_view()(
            factory.get(f'/ticket/events/{self.event.id}/ticket-types/'),
            event_id=self.event.id,
        )
        owner_request = factory.get(f'/ticket/events/{self.event.id}/ticket-types/')
        force_authenticate(owner_request, user=self.host)
        owner_response = TicketTypeListCreateView.as_view()(
            owner_request, event_id=self.event.id
        )

        self.assertEqual(anonymous_response.status_code, 404)
        self.assertEqual(owner_response.status_code, 200)

    def test_inactive_ticket_types_are_hidden_from_public(self):
        self.event.is_active = False
        self.event.save(update_fields=['is_active'])

        response = TicketTypeListCreateView.as_view()(
            APIRequestFactory().get(f'/ticket/events/{self.event.id}/ticket-types/'),
            event_id=self.event.id,
        )

        self.assertEqual(response.status_code, 404)

    def test_ticket_type_creation_requires_an_available_event(self):
        self.event.is_active = False
        self.event.save(update_fields=['is_active'])
        request = APIRequestFactory().post(
            f'/ticket/events/{self.event.id}/ticket-types/',
            {
                'name': 'Late ticket type',
                'price': '2000.00',
                'quantity_total': 5,
            },
            format='json',
        )
        force_authenticate(request, user=self.host)

        response = TicketTypeListCreateView.as_view()(request, event_id=self.event.id)

        self.assertEqual(response.status_code, 400)
        self.assertEqual(TicketType.objects.filter(event=self.event).count(), 1)

    def test_host_can_prepare_ticket_types_for_a_future_draft(self):
        self.event.status = 'draft'
        self.event.save(update_fields=['status'])
        request = APIRequestFactory().post(
            f'/ticket/events/{self.event.id}/ticket-types/',
            {
                'name': 'Draft regular',
                'price': '2000.00',
                'quantity_total': 5,
            },
            format='json',
        )
        force_authenticate(request, user=self.host)

        response = TicketTypeListCreateView.as_view()(request, event_id=self.event.id)

        self.assertEqual(response.status_code, 201)
        self.assertEqual(TicketType.objects.filter(event=self.event).count(), 2)

    def test_second_check_in_is_rejected(self):
        self._make_event_live()
        ticket = Ticket.objects.create(ticket_type=self.ticket_type, user=self.buyer)
        factory = APIRequestFactory()

        first_request = factory.post('/ticket/check-in/', {'ticket_code': ticket.ticket_code}, format='json')
        force_authenticate(first_request, user=self.host)
        first_response = TicketCheckInView.as_view()(first_request)

        second_request = factory.post('/ticket/check-in/', {'ticket_code': ticket.ticket_code}, format='json')
        force_authenticate(second_request, user=self.host)
        second_response = TicketCheckInView.as_view()(second_request)

        self.assertEqual(first_response.status_code, 200)
        self.assertEqual(second_response.status_code, 400)

    def test_deleting_event_with_issued_tickets_cancels_instead(self):
        ticket = Ticket.objects.create(ticket_type=self.ticket_type, user=self.buyer)
        request = APIRequestFactory().delete(f'/event/{self.event.id}/')
        force_authenticate(request, user=self.host)

        response = EventDetailView.as_view()(request, pk=self.event.id)

        self.assertEqual(response.status_code, 200)
        self.event.refresh_from_db()
        self.assertEqual(self.event.status, 'cancelled')
        self.assertFalse(self.event.is_active)
        self.assertTrue(Ticket.objects.filter(pk=ticket.pk).exists())
