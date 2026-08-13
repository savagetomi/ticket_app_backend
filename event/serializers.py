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

    # def get_cover_image(self, obj):
    #     if not obj.cover_image:
    #         return None

    #     return obj.cover_image.url