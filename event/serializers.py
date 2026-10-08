import math

from rest_framework import serializers
from .models import Event


class EventSerializer(serializers.ModelSerializer):
    host = serializers.CharField(source='host.username', read_only=True)
    is_sold_out = serializers.BooleanField(read_only=True)
    cover_image = serializers.ImageField(required=False, allow_null=True)



    class Meta:
        model = Event
        fields = [
            'id', 'host', 'title', 'description', 'category', 'cover_image',
            'venue_name', 'address', 'city', 'state', 'country',
            'latitude', 'longitude', 'start_datetime', 'end_datetime',
            'status', 'is_sold_out', 'created_at', 'updated_at',
        ]
        read_only_fields = ['id', 'host', 'created_at', 'updated_at']


    def validate(self, attrs):
        latitude = attrs.get('latitude', getattr(self.instance, 'latitude', None))
        longitude = attrs.get('longitude', getattr(self.instance, 'longitude', None))
        event_status = attrs.get('status', getattr(self.instance, 'status', 'draft'))
        start_datetime = attrs.get('start_datetime', getattr(self.instance, 'start_datetime', None))
        end_datetime = attrs.get('end_datetime', getattr(self.instance, 'end_datetime', None))

        if event_status == 'published' and (latitude is None or longitude is None):
            raise serializers.ValidationError({
                'location': 'Published events must have a valid latitude and longitude.'
            })

        if start_datetime and end_datetime and end_datetime <= start_datetime:
            raise serializers.ValidationError({
                'end_datetime': 'The event must end after it starts.'
            })

        return attrs

    def validate_latitude(self, value):
        if not math.isfinite(value) or not -90 <= value <= 90:
            raise serializers.ValidationError('Latitude must be a finite value between -90 and 90.')
        return value

    def validate_longitude(self, value):
        if not math.isfinite(value) or not -180 <= value <= 180:
            raise serializers.ValidationError('Longitude must be a finite value between -180 and 180.')
        return value

    # def get_cover_image(self, obj):
    #     if not obj.cover_image:
    #         return None

    #     return obj.cover_image.url


class NearbyEventQuerySerializer(serializers.Serializer):
    """Validate a deliberately small, bounded public geo-search request."""

    ALLOWED_RADII_KM = (5, 10, 20, 30)
    MAX_PAGE = 1000

    latitude = serializers.FloatField(required=True)
    longitude = serializers.FloatField(required=True)
    radius_km = serializers.IntegerField(required=False, default=5)
    page = serializers.IntegerField(required=False, default=1, min_value=1, max_value=MAX_PAGE)

    @staticmethod
    def _validate_finite_coordinate(value, minimum, maximum, name):
        if not math.isfinite(value) or not minimum <= value <= maximum:
            raise serializers.ValidationError(
                f'{name} must be a finite value between {minimum} and {maximum}.'
            )
        return value

    def validate_latitude(self, value):
        return self._validate_finite_coordinate(value, -90, 90, 'Latitude')

    def validate_longitude(self, value):
        return self._validate_finite_coordinate(value, -180, 180, 'Longitude')

    def validate_radius_km(self, value):
        if value not in self.ALLOWED_RADII_KM:
            allowed = ', '.join(str(radius) for radius in self.ALLOWED_RADII_KM)
            raise serializers.ValidationError(f'Radius must be one of: {allowed} km.')
        return value


class NearbyEventSerializer(serializers.ModelSerializer):
    """Public nearby-search representation with database-calculated distance."""

    distance_km = serializers.FloatField(read_only=True)

    class Meta:
        model = Event
        fields = [
            'id', 'title', 'description', 'category', 'cover_image',
            'venue_name', 'address', 'city', 'state', 'country',
            'latitude', 'longitude', 'start_datetime', 'end_datetime',
            'distance_km',
        ]
        read_only_fields = fields
