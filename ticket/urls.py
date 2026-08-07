from django.urls import path
from .views import TicketTypeListCreateView, TicketPurchaseView, MyTicketsView, TicketCheckInView

urlpatterns = [
    path('events/<uuid:event_id>/ticket-types/', TicketTypeListCreateView.as_view(), name='ticket-type-list-create'),
    path('purchase/', TicketPurchaseView.as_view(), name='ticket-purchase'),
    path('my-ticket/', MyTicketsView.as_view(), name='my-tickets'),
    path('check-in/', TicketCheckInView.as_view(), name='ticket-check-in'),
]