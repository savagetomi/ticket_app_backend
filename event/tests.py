from datetime import timedelta
from io import StringIO
import math

from django.core.cache import cache
from django.core.management import call_command
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient, APIRequestFactory, force_authenticate

from user.models import CustomUser

from .models import Event
from .views import EventDetailView


class EventVisibilityTests(TestCase):
    def setUp(self):
        self.host = CustomUser.objects.create_user(
            username='event-host',
            email_address='event-host@example.com',
            first_name='Event',
            last_name='Host',
            phone_number='08000000008',
            password='SafePassword123!',
            roles='host',
        )
        self.other_user = CustomUser.objects.create_user(
            username='event-viewer',
            email_address='event-viewer@example.com',
            first_name='Event',
            last_name='Viewer',
            phone_number='08000000009',
            password='SafePassword123!',
        )
        now = timezone.now()
        self.event = Event.objects.create(
            host=self.host,
            title='Private Draft',
            venue_name='Private Venue',
            address='2 Test Street',
            city='Lagos',
            start_datetime=now + timedelta(days=1),
            end_datetime=now + timedelta(days=1, hours=2),
            status='draft',
        )
        self.factory = APIRequestFactory()

    def test_draft_detail_is_hidden_from_public_and_other_users(self):
        anonymous_request = self.factory.get(f'/event/{self.event.id}/')
        anonymous_response = EventDetailView.as_view()(anonymous_request, pk=self.event.id)

        other_request = self.factory.get(f'/event/{self.event.id}/')
        force_authenticate(other_request, user=self.other_user)
        other_response = EventDetailView.as_view()(other_request, pk=self.event.id)

        self.assertEqual(anonymous_response.status_code, 404)
        self.assertEqual(other_response.status_code, 404)

    def test_host_can_retrieve_own_draft(self):
        request = self.factory.get(f'/event/{self.event.id}/')
        force_authenticate(request, user=self.host)

        response = EventDetailView.as_view()(request, pk=self.event.id)

        self.assertEqual(response.status_code, 200)


class EventActivityLifecycleTests(TestCase):
    def setUp(self):
        cache.clear()
        self.host = CustomUser.objects.create_user(
            username='activity-host',
            email_address='activity-host@example.com',
            first_name='Activity',
            last_name='Host',
            phone_number='08000000011',
            password='SafePassword123!',
            roles='host',
        )
        self.now = timezone.now()
        self.client = APIClient()

    def tearDown(self):
        cache.clear()
        super().tearDown()

    def _event(self, title, start_delta=timedelta(hours=2), host=None, **kwargs):
        return Event.objects.create(
            host=host or self.host,
            title=title,
            venue_name=f'{title} venue',
            address='5 Lifecycle Street',
            city='Lagos',
            latitude=6.5244,
            longitude=3.3792,
            start_datetime=self.now + start_delta,
            end_datetime=kwargs.pop('end_datetime', self.now + start_delta + timedelta(hours=2)),
            status=kwargs.pop('status', 'published'),
            **kwargs,
        )

    def test_due_events_are_persistently_deactivated(self):
        future = self._event('Future event')
        imminent = self._event('Imminent event', start_delta=timedelta(seconds=30))
        past = self._event(
            'Past event',
            start_delta=-timedelta(hours=2),
            end_datetime=self.now - timedelta(hours=1),
        )

        self.assertTrue(future.is_active)
        self.assertFalse(imminent.is_active)
        self.assertFalse(past.is_active)

        # QuerySet.update bypasses model save; the lifecycle job must still
        # correct stale data atomically.
        Event.objects.filter(pk=imminent.pk).update(is_active=True)
        Event.deactivate_due_events(self.now)
        imminent.refresh_from_db()
        self.assertFalse(imminent.is_active)

    def test_public_discovery_hides_inactive_due_and_inactive_host_events(self):
        visible = self._event('Visible event')
        inactive = self._event('Inactive event')
        Event.objects.filter(pk=inactive.pk).update(is_active=False)
        imminent = self._event('Imminent event', start_delta=timedelta(seconds=30))
        disabled_host = CustomUser.objects.create_user(
            username='disabled-event-host',
            email_address='disabled-event-host@example.com',
            first_name='Disabled',
            last_name='Host',
            phone_number='08000000012',
            password='SafePassword123!',
            roles='host',
        )
        hidden_by_host = self._event('Disabled host event', host=disabled_host)
        disabled_host.is_active = False
        disabled_host.save(update_fields=['is_active'])

        listed = self.client.get(reverse('event-list-create'))
        nearby = self.client.get(
            reverse('nearby-events'),
            {'latitude': 6.5244, 'longitude': 3.3792},
        )
        anonymous_detail = self.client.get(
            reverse('event-detail', args=[inactive.pk])
        )
        owner_client = APIClient()
        owner_client.force_authenticate(self.host)
        owner_detail = owner_client.get(reverse('event-detail', args=[inactive.pk]))

        list_ids = {item['id'] for item in listed.data}
        nearby_ids = {item['id'] for item in nearby.data['results']}
        self.assertEqual(list_ids, {str(visible.pk)})
        self.assertEqual(nearby_ids, {str(visible.pk)})
        self.assertNotIn(str(imminent.pk), list_ids)
        self.assertNotIn(str(hidden_by_host.pk), list_ids)
        self.assertEqual(anonymous_detail.status_code, 404)
        self.assertEqual(owner_detail.status_code, 200)

    def test_host_delete_soft_deactivates_event(self):
        event = self._event('Soft deleted event')
        self.client.force_authenticate(self.host)

        response = self.client.delete(reverse('event-detail', args=[event.pk]))

        self.assertEqual(response.status_code, 200)
        event.refresh_from_db()
        self.assertEqual(event.status, 'cancelled')
        self.assertFalse(event.is_active)
        self.assertTrue(Event.objects.filter(pk=event.pk).exists())

    def test_scheduled_command_deactivates_stale_event(self):
        due_event = self._event('Cron deactivation', start_delta=timedelta(seconds=30))
        Event.objects.filter(pk=due_event.pk).update(is_active=True)
        output = StringIO()

        call_command('deactivate_due_events', stdout=output)

        due_event.refresh_from_db()
        self.assertFalse(due_event.is_active)
        self.assertIn('Deactivated 1 event(s).', output.getvalue())


class NearbyEventsTests(TestCase):
    BASE_LATITUDE = 6.5244
    BASE_LONGITUDE = 3.3792

    def setUp(self):
        cache.clear()
        self.host = CustomUser.objects.create_user(
            username='nearby-host',
            email_address='nearby-host@example.com',
            first_name='Nearby',
            last_name='Host',
            phone_number='08000000010',
            password='SafePassword123!',
            roles='host',
        )
        self.client = APIClient()
        self.url = reverse('nearby-events')
        self.now = timezone.now()

    def tearDown(self):
        cache.clear()
        super().tearDown()

    def _event(self, title, latitude, longitude, status='published', end_datetime=None):
        return Event.objects.create(
            host=self.host,
            title=title,
            venue_name=f'{title} venue',
            address='3 Nearby Street',
            city='Lagos',
            latitude=latitude,
            longitude=longitude,
            start_datetime=self.now + timedelta(hours=1),
            end_datetime=end_datetime or self.now + timedelta(hours=3),
            status=status,
        )

    def test_canonical_route_returns_only_active_published_events(self):
        exact = self._event('Exact match', self.BASE_LATITUDE, self.BASE_LONGITUDE)
        nearby = self._event('Nearby match', self.BASE_LATITUDE + 0.03, self.BASE_LONGITUDE)
        self._event('Draft match', self.BASE_LATITUDE, self.BASE_LONGITUDE, status='draft')
        self._event('Cancelled match', self.BASE_LATITUDE, self.BASE_LONGITUDE, status='cancelled')
        self._event('Completed match', self.BASE_LATITUDE, self.BASE_LONGITUDE, status='completed')
        self._event(
            'Ended match',
            self.BASE_LATITUDE,
            self.BASE_LONGITUDE,
            end_datetime=self.now - timedelta(minutes=1),
        )
        self._event('No coordinates', None, None)

        response = self.client.get(
            self.url,
            {'latitude': self.BASE_LATITUDE, 'longitude': self.BASE_LONGITUDE},
        )

        self.assertEqual(self.url, '/events/nearby/')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['radius_km'], 5)
        self.assertEqual(response.data['pagination']['page_size'], 10)
        self.assertEqual(response.data['pagination']['total_pages'], 1)
        result_ids = {result['id'] for result in response.data['results']}
        self.assertEqual(result_ids, {str(exact.id), str(nearby.id)})
        self.assertAlmostEqual(response.data['results'][0]['distance_km'], 0.0, places=2)

    def test_radius_options_are_bounded_and_results_are_distance_sorted(self):
        exact = self._event('At base', self.BASE_LATITUDE, self.BASE_LONGITUDE)
        within_five = self._event('Within five', self.BASE_LATITUDE + 0.04, self.BASE_LONGITUDE)
        within_ten = self._event('Within ten', self.BASE_LATITUDE + 0.08, self.BASE_LONGITUDE)
        outside_ten = self._event('Outside ten', self.BASE_LATITUDE + 0.15, self.BASE_LONGITUDE)

        default_response = self.client.get(
            self.url,
            {'latitude': self.BASE_LATITUDE, 'longitude': self.BASE_LONGITUDE},
        )
        ten_km_response = self.client.get(
            self.url,
            {'latitude': self.BASE_LATITUDE, 'longitude': self.BASE_LONGITUDE, 'radius': 10},
        )

        default_ids = [result['id'] for result in default_response.data['results']]
        ten_km_ids = [result['id'] for result in ten_km_response.data['results']]
        self.assertEqual(default_ids, [str(exact.id), str(within_five.id)])
        self.assertEqual(ten_km_ids, [str(exact.id), str(within_five.id), str(within_ten.id)])
        self.assertNotIn(str(outside_ten.id), ten_km_ids)
        distances = [result['distance_km'] for result in ten_km_response.data['results']]
        self.assertEqual(distances, sorted(distances))

    def test_invalid_or_ambiguous_query_parameters_are_rejected(self):
        invalid_queries = (
            ({'longitude': self.BASE_LONGITUDE}, 'latitude'),
            ({'latitude': self.BASE_LATITUDE}, 'longitude'),
            ({'latitude': 'NaN', 'longitude': self.BASE_LONGITUDE}, 'latitude'),
            ({'latitude': 'Infinity', 'longitude': self.BASE_LONGITUDE}, 'latitude'),
            ({'latitude': 91, 'longitude': self.BASE_LONGITUDE}, 'latitude'),
            ({'latitude': self.BASE_LATITUDE, 'longitude': 181}, 'longitude'),
            ({'latitude': self.BASE_LATITUDE, 'longitude': self.BASE_LONGITUDE, 'radius_km': 4}, 'radius_km'),
            ({'latitude': self.BASE_LATITUDE, 'longitude': self.BASE_LONGITUDE, 'page': 0}, 'page'),
            ({'latitude': self.BASE_LATITUDE, 'longitude': self.BASE_LONGITUDE, 'page': 1001}, 'page'),
            ({'latitude': self.BASE_LATITUDE, 'longitude': self.BASE_LONGITUDE, 'page': 'not-a-page'}, 'page'),
        )

        for query, field in invalid_queries:
            with self.subTest(query=query):
                response = self.client.get(self.url, query)
                self.assertEqual(response.status_code, 400)
                self.assertIn(field, response.data)

        duplicate = self.client.get(
            f'{self.url}?latitude={self.BASE_LATITUDE}&longitude={self.BASE_LONGITUDE}&radius_km=5&radius_km=10'
        )
        duplicate_page = self.client.get(
            f'{self.url}?latitude={self.BASE_LATITUDE}&longitude={self.BASE_LONGITUDE}&page=1&page=2'
        )
        conflicting = self.client.get(
            self.url,
            {
                'latitude': self.BASE_LATITUDE,
                'longitude': self.BASE_LONGITUDE,
                'radius_km': 5,
                'radius': 10,
            },
        )
        unsupported = self.client.get(
            self.url,
            {
                'latitude': self.BASE_LATITUDE,
                'longitude': self.BASE_LONGITUDE,
                'page_size': 999999,
            },
        )
        self.assertEqual(duplicate.status_code, 400)
        self.assertEqual(duplicate_page.status_code, 400)
        self.assertEqual(conflicting.status_code, 400)
        self.assertEqual(unsupported.status_code, 400)

    def test_pagination_returns_ten_nearest_events_first(self):
        events = [
            self._event(
                f'Paginated {index}',
                self.BASE_LATITUDE + index * 0.001,
                self.BASE_LONGITUDE,
            )
            for index in range(21)
        ]

        pages = [
            self.client.get(
                self.url,
                {
                    'latitude': self.BASE_LATITUDE,
                    'longitude': self.BASE_LONGITUDE,
                    'radius_km': 5,
                    'page': page_number,
                },
            )
            for page_number in (1, 2, 3)
        ]

        self.assertTrue(all(response.status_code == 200 for response in pages))
        self.assertEqual([len(response.data['results']) for response in pages], [10, 10, 1])
        self.assertEqual(pages[0].data['count'], 21)
        self.assertEqual(
            pages[0].data['pagination'],
            {
                'page': 1,
                'page_size': 10,
                'total_pages': 3,
                'total_results': 21,
                'has_next': True,
                'has_previous': False,
                'next_page': 2,
                'previous_page': None,
            },
        )
        self.assertEqual(pages[2].data['pagination']['next_page'], None)
        self.assertEqual(pages[2].data['pagination']['previous_page'], 2)

        returned_ids = [
            result['id']
            for response in pages
            for result in response.data['results']
        ]
        self.assertEqual(returned_ids, [str(event.id) for event in events])
        self.assertTrue(
            all(
                first['distance_km'] <= second['distance_km']
                for response in pages
                for first, second in zip(response.data['results'], response.data['results'][1:])
            )
        )

    def test_out_of_range_page_is_not_silently_clamped(self):
        self._event('Only result', self.BASE_LATITUDE, self.BASE_LONGITUDE)

        response = self.client.get(
            self.url,
            {
                'latitude': self.BASE_LATITUDE,
                'longitude': self.BASE_LONGITUDE,
                'page': 2,
            },
        )

        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.data['detail'], 'Invalid page.')

    def test_antimeridian_search_and_fixed_page_size(self):
        near_dateline = self._event('Across date line', 0, 179.98)
        response = self.client.get(
            self.url,
            {'latitude': 0, 'longitude': -179.98, 'radius_km': 5},
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn(str(near_dateline.id), {result['id'] for result in response.data['results']})

        Event.objects.bulk_create([
            Event(
                host=self.host,
                title=f'Capped {index}',
                venue_name='Capped venue',
                address='4 Nearby Street',
                city='Lagos',
                latitude=self.BASE_LATITUDE + index * 0.00001,
                longitude=self.BASE_LONGITUDE,
                start_datetime=self.now + timedelta(hours=1),
                end_datetime=self.now + timedelta(hours=3),
                status='published',
            )
            for index in range(51)
        ])
        capped = self.client.get(
            self.url,
            {
                'latitude': self.BASE_LATITUDE,
                'longitude': self.BASE_LONGITUDE,
                'radius_km': 5,
            },
        )

        self.assertEqual(capped.status_code, 200)
        self.assertEqual(capped.data['count'], 51)
        self.assertEqual(len(capped.data['results']), 10)
        self.assertEqual(capped.data['pagination']['total_pages'], 6)
        self.assertTrue(all(math.isfinite(result['distance_km']) for result in capped.data['results']))
