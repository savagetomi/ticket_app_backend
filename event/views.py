import math

from django.core.paginator import EmptyPage, Paginator
from django.db.models import ExpressionWrapper, F, FloatField, Q, Value
from django.db.models.functions import ASin, Cos, Greatest, Least, Radians, Sin, Sqrt
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import status
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView
from drf_spectacular.utils import extend_schema, OpenApiResponse

from user.permissions import IsActiveAuthenticatedOrReadOnly, IsHost
from .models import Event
from .permissions import IsEventOwnerOrReadOnly
from .serializers import EventSerializer, NearbyEventQuerySerializer, NearbyEventSerializer
from rest_framework.parsers import MultiPartParser, FormParser,JSONParser


class NearbyEventsView(APIView):
    """Return a bounded, public list of active events near a coordinate."""

    permission_classes = [AllowAny]
    throttle_scope = 'nearby_events'

    EARTH_RADIUS_KM = 6371.0088
    PAGE_SIZE = 10

    @staticmethod
    def _distance_expression(latitude, longitude):
        """Haversine distance in kilometres, calculated by the database."""
        float_value = lambda value: Value(value, output_field=FloatField())
        query_latitude = float_value(math.radians(latitude))
        query_longitude = float_value(math.radians(longitude))
        half = float_value(0.5)

        latitude_delta = Radians(F('latitude')) - query_latitude
        longitude_delta = Radians(F('longitude')) - query_longitude
        latitude_component = Sin(latitude_delta * half) * Sin(latitude_delta * half)
        longitude_component = Sin(longitude_delta * half) * Sin(longitude_delta * half)
        haversine = ExpressionWrapper(
            latitude_component
            + Cos(query_latitude) * Cos(Radians(F('latitude'))) * longitude_component,
            output_field=FloatField(),
        )
        # Floating-point rounding can make values just outside [0, 1]. Clamp
        # before ASin/Sqrt so same-point and edge coordinates cannot raise a
        # database math-domain error.
        clamped_haversine = Greatest(
            float_value(0.0),
            Least(float_value(1.0), haversine),
        )
        return ExpressionWrapper(
            float_value(2 * NearbyEventsView.EARTH_RADIUS_KM)
            * ASin(Sqrt(clamped_haversine)),
            output_field=FloatField(),
        )

    @staticmethod
    def _bounded_candidates(latitude, longitude, radius_km, now):
        """Coarsely restrict rows before applying the exact Haversine filter."""
        latitude_delta = radius_km / 111.32
        cosine_latitude = abs(math.cos(math.radians(latitude)))
        longitude_delta = (
            180
            if cosine_latitude < 1e-12
            else min(180, radius_km / (111.32 * cosine_latitude))
        )

        events = Event.objects.publicly_available(now).filter(
            latitude__isnull=False,
            longitude__isnull=False,
            latitude__gte=max(-90, latitude - latitude_delta),
            latitude__lte=min(90, latitude + latitude_delta),
            longitude__gte=-180,
            longitude__lte=180,
        )

        minimum_longitude = longitude - longitude_delta
        maximum_longitude = longitude + longitude_delta
        if longitude_delta >= 180:
            return events
        if minimum_longitude < -180:
            return events.filter(
                Q(longitude__gte=minimum_longitude + 360)
                | Q(longitude__lte=maximum_longitude)
            )
        if maximum_longitude > 180:
            return events.filter(
                Q(longitude__gte=minimum_longitude)
                | Q(longitude__lte=maximum_longitude - 360)
            )
        return events.filter(
            longitude__gte=minimum_longitude,
            longitude__lte=maximum_longitude,
        )

    @extend_schema(
        tags=['Events'],
        summary='Find nearby events',
        description=(
            'Public. Supply latitude and longitude plus an optional radius_km '
            '(or radius) of 5, 10, 20, or 30 and an optional page (1-1000). '
            'Returns up to 10 published, ongoing or upcoming events per '
            'page, ordered by distance.'
        ),
        responses={
            200: OpenApiResponse(description='Nearby events returned.'),
            400: OpenApiResponse(description='Invalid coordinate or radius.'),
            404: OpenApiResponse(description='Requested page does not exist.'),
            429: OpenApiResponse(description='Rate limit exceeded.'),
        },
    )
    def get(self, request):
        allowed_parameters = {'latitude', 'longitude', 'radius_km', 'radius', 'page'}
        unsupported_parameters = set(request.query_params) - allowed_parameters
        if unsupported_parameters:
            return Response(
                {
                    name: ['This query parameter is not supported.']
                    for name in sorted(unsupported_parameters)
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        for name in ('latitude', 'longitude', 'radius_km', 'radius', 'page'):
            if len(request.query_params.getlist(name)) > 1:
                return Response(
                    {name: ['Provide this query parameter only once.']},
                    status=status.HTTP_400_BAD_REQUEST,
                )
        if 'radius_km' in request.query_params and 'radius' in request.query_params:
            return Response(
                {'radius_km': ['Use either radius_km or radius, not both.']},
                status=status.HTTP_400_BAD_REQUEST,
            )

        parameters = request.query_params.copy()
        if 'radius' in parameters:
            parameters['radius_km'] = parameters['radius']
        query = NearbyEventQuerySerializer(data=parameters)
        if not query.is_valid():
            return Response(query.errors, status=status.HTTP_400_BAD_REQUEST)

        latitude = query.validated_data['latitude']
        longitude = query.validated_data['longitude']
        radius_km = query.validated_data['radius_km']
        page_number = query.validated_data['page']
        now = timezone.now()
        Event.deactivate_due_events(now)
        distance_expression = self._distance_expression(latitude, longitude)
        events = (
            self._bounded_candidates(latitude, longitude, radius_km, now)
            .annotate(distance_km=distance_expression)
            .filter(distance_km__lte=radius_km)
            .order_by('distance_km', 'start_datetime', 'id')
        )
        paginator = Paginator(events, self.PAGE_SIZE)
        try:
            event_page = paginator.page(page_number)
        except EmptyPage:
            return Response(
                {'detail': 'Invalid page.'},
                status=status.HTTP_404_NOT_FOUND,
            )

        results = NearbyEventSerializer(
            event_page.object_list,
            many=True,
            context={'request': request},
        ).data
        for result in results:
            result['distance_km'] = round(result['distance_km'], 2)

        return Response(
            {
                'success': True,
                'radius_km': radius_km,
                'count': paginator.count,
                'pagination': {
                    'page': event_page.number,
                    'page_size': self.PAGE_SIZE,
                    'total_pages': paginator.num_pages,
                    'total_results': paginator.count,
                    'has_next': event_page.has_next(),
                    'has_previous': event_page.has_previous(),
                    'next_page': event_page.next_page_number() if event_page.has_next() else None,
                    'previous_page': (
                        event_page.previous_page_number()
                        if event_page.has_previous()
                        else None
                    ),
                },
                'results': results,
            },
            status=status.HTTP_200_OK,
        )


class EventListCreateView(APIView):
    parser_classes = [MultiPartParser, FormParser, JSONParser]  # was a dead local var inside get_permissions

    def get_permissions(self):
        if self.request.method == 'POST':
            return [IsHost()]
        return [AllowAny()]

    @extend_schema(
        tags=['Events'],
        summary="List published events",
        description="Returns all published events. Public — no authentication required.",
        responses={200: EventSerializer(many=True)}
    )
    def get(self, request):
        now = timezone.now()
        Event.deactivate_due_events(now)
        events = Event.objects.publicly_available(now).order_by('-start_datetime')
        return Response(
            EventSerializer(events, many=True, context={"request": request}).data
        )

    @extend_schema(
        tags=['Events'],
        summary="Create a new event",
        description="Creates a new event owned by the requesting host, saved with status='draft'. Restricted to authenticated users with the 'host' role.",
        request=EventSerializer,
        responses={
            201: OpenApiResponse(description="Event created"),
            400: OpenApiResponse(description="Validation errors"),
            403: OpenApiResponse(description="Only hosts can create events"),
        }
    )
    def post(self, request):
        serializer = EventSerializer(data=request.data)

        if serializer.is_valid():
            event = serializer.save(host=request.user)

            return Response(
                {
                    'success': True,
                    'message': 'Event created successfully',
                    'event': EventSerializer(
                        event,
                        context={"request": request}
                    ).data,
                },
                status=status.HTTP_201_CREATED
            )

        return Response(
            serializer.errors,
            status=status.HTTP_400_BAD_REQUEST
        )


class EventDetailView(APIView):
    parser_classes = [MultiPartParser, FormParser, JSONParser]
    permission_classes = [IsActiveAuthenticatedOrReadOnly, IsEventOwnerOrReadOnly]

    def get_object(self, pk):
        # Inactive/draft/cancelled metadata is visible only to its host. The
        # public detail endpoint must mirror the public list endpoint.
        now = timezone.now()
        Event.deactivate_due_events(now)
        events = Event.objects.filter(pk=pk)
        if self.request.user.is_authenticated:
            events = events.filter(
                Event.public_availability_filter(now) | Q(host=self.request.user)
            )
        else:
            events = events.filter(Event.public_availability_filter(now))
        event = get_object_or_404(events)
        self.check_object_permissions(self.request, event)
        return event

    @extend_schema(
        tags=['Events'],
        summary="Retrieve a single event",
        description="Public for active, available published events; hosts may also retrieve their own inactive or non-public events.",
        responses={200: EventSerializer}
    )
    def get(self, request, pk):
        event = self.get_object(pk)
        serializer = EventSerializer(event, context={"request": request})
        return Response(serializer.data)

    @extend_schema(
        tags=['Events'],
        summary="Replace an event",
        description="Full update — all fields must be provided. Only the owning host can update.",
        request=EventSerializer,
        responses={
            200: OpenApiResponse(description="Event updated"),
            400: OpenApiResponse(description="Validation errors"),
            403: OpenApiResponse(description="Not the event owner"),
        }
    )
    def put(self, request, pk):
        event = self.get_object(pk)
        serializer = EventSerializer(event, data=request.data, context={"request": request})
        if serializer.is_valid():
            serializer.save()
            return Response(
                {'success': True, 'message': 'Event updated successfully', 'event': serializer.data},
                status=status.HTTP_200_OK
            )
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    @extend_schema(
        tags=['Events'],
        summary="Partially update an event",
        description="Only send the fields you want to change. Only the owning host can update.",
        request=EventSerializer,
        responses={
            200: OpenApiResponse(description="Event updated"),
            400: OpenApiResponse(description="Validation errors"),
            403: OpenApiResponse(description="Not the event owner"),
        }
    )
    def patch(self, request, pk):
        event = self.get_object(pk)
        serializer = EventSerializer(event, data=request.data, partial=True, context={"request": request})
        if serializer.is_valid():
            serializer.save()
            return Response(
                {'success': True, 'message': 'Event updated successfully', 'event': serializer.data},
                status=status.HTTP_200_OK
            )
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    @extend_schema(
        tags=['Events'],
        summary="Deactivate an event",
        description="Only the owning host can deactivate. The event remains in the database for history and administration.",
        responses={200: OpenApiResponse(description="Event deactivated")}
    )
    def delete(self, request, pk):
        event = self.get_object(pk)
        # Retain the event and any related tickets for audit/history instead
        # of cascading a host deletion through admission records.
        event.status = 'cancelled'
        event.is_active = False
        event.save(update_fields=['status', 'is_active', 'updated_at'])
        return Response(
            {'success': True, 'message': 'Event deactivated successfully.'},
            status=status.HTTP_200_OK,
        )


class MyEventsView(APIView):
    permission_classes = [IsHost]

    @extend_schema(
        tags=['Events'],
        summary="List my events",
        description="Returns every event (any status — draft, published, cancelled) created by the authenticated host. Powers the host dashboard/home screen.",
        responses={200: EventSerializer(many=True)}
    )
    def get(self, request):
        Event.deactivate_due_events()
        events = Event.objects.filter(host=request.user)
        return Response(
            EventSerializer(events, many=True, context={"request": request}).data
        )
