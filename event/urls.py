from django.urls import path
from .views import EventListCreateView, EventDetailView, MyEventsView

urlpatterns = [
    path('', EventListCreateView.as_view(), name='event-list-create'),
    path('mine/', MyEventsView.as_view(), name='my-events'),
    path('<uuid:pk>/', EventDetailView.as_view(), name='event-detail'),
]