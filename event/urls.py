from django.urls import path
from .views import EventListCreateView, EventDetailView, MyEventsView, NearbyEventsView

urlpatterns = [
    # Compatibility route under the existing singular API prefix. The public
    # canonical route requested by clients is /events/nearby/.
    path('nearby/', NearbyEventsView.as_view(), name='nearby-events-legacy'),
    path('', EventListCreateView.as_view(), name='event-list-create'),
    path('mine/', MyEventsView.as_view(), name='my-events'),
    path('<uuid:pk>/', EventDetailView.as_view(), name='event-detail'),
]
