from urllib import request

from django.shortcuts import get_object_or_404
from rest_framework import status
from rest_framework.permissions import AllowAny, IsAuthenticatedOrReadOnly
from rest_framework.response import Response
from rest_framework.views import APIView
from drf_spectacular.utils import extend_schema, OpenApiResponse

from user.permissions import IsHost  # adjust to match your actual app name
from .models import Event
from .permissions import IsEventOwnerOrReadOnly
from .serializers import EventSerializer
from rest_framework.parsers import MultiPartParser, FormParser,JSONParser


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
        events = Event.objects.filter(status='published').order_by('-start_datetime')  # NOTE: see caveat above — draft vs published
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
        print("REQUEST DATA:", request.data)
        print("REQUEST FILES:", request.FILES)

        serializer = EventSerializer(data=request.data)

        if serializer.is_valid():
            event = serializer.save(host=request.user)

            print("SAVED IMAGE:", event.cover_image.name)

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

        print("SERIALIZER ERRORS:", serializer.errors)

        return Response(
            serializer.errors,
            status=status.HTTP_400_BAD_REQUEST
        )


class EventDetailView(APIView):
    parser_classes = [MultiPartParser, FormParser, JSONParser]
    permission_classes = [IsAuthenticatedOrReadOnly, IsEventOwnerOrReadOnly]

    def get_object(self, pk):
        event = get_object_or_404(Event, pk=pk)
        self.check_object_permissions(self.request, event)
        return event

    @extend_schema(
        tags=['Events'],
        summary="Retrieve a single event",
        description="Public.",
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
        summary="Delete an event",
        description="Only the owning host can delete.",
        responses={200: OpenApiResponse(description="Event deleted")}
    )
    def delete(self, request, pk):
        event = self.get_object(pk)
        event.delete()
        return Response({'success': True, 'message': 'Event deleted successfully'}, status=status.HTTP_200_OK)


class MyEventsView(APIView):
    permission_classes = [IsHost]

    @extend_schema(
        tags=['Events'],
        summary="List my events",
        description="Returns every event (any status — draft, published, cancelled) created by the authenticated host. Powers the host dashboard/home screen.",
        responses={200: EventSerializer(many=True)}
    )
    def get(self, request):
        events = Event.objects.filter(host=request.user)
        return Response(
            EventSerializer(events, many=True, context={"request": request}).data
        )