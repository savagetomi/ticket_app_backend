from django.urls import path
from .views import (
    GenerateOTPView,
    InactiveUserDetailView,
    LoginView,
    LogoutView,
    ProfileView,
    ReactivateUserView,
    RefreshTokenView,
    RegisterView,
    ResendOTPView,
    VerifyOTPView,
)

urlpatterns = [
    path('register/', RegisterView.as_view(), name='register'),
    path('login/', LoginView.as_view(), name='login'),
    path('logout/', LogoutView.as_view(), name='logout'),
    path('verify-otp/', VerifyOTPView.as_view()),
    path('resend-otp/', ResendOTPView.as_view()),
    path('gen-otp/', GenerateOTPView.as_view()),
    path('profile/', ProfileView.as_view(), name='profile'),
    path('refresh/', RefreshTokenView.as_view(), name='token-refresh'),
    path(
        'admin/users/<uuid:user_id>/',
        InactiveUserDetailView.as_view(),
        name='admin-inactive-user-detail',
    ),
    path(
        'admin/users/<uuid:user_id>/reactivate/',
        ReactivateUserView.as_view(),
        name='admin-reactivate-user',
    ),
]
