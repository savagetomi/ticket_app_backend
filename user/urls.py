from django.urls import path
from .views import RegisterView, LoginView, LogoutView, ProfileView, VerifyOTPView, ResendOTPView, GenerateOTPView, RefreshTokenView

urlpatterns = [
    path('register/', RegisterView.as_view(), name='register'),
    path('login/', LoginView.as_view(), name='login'),
    path('logout/', LogoutView.as_view(), name='logout'),
    path('verify-otp/', VerifyOTPView.as_view()),
    path('resend-otp/', ResendOTPView.as_view()),
    path('gen-otp/', GenerateOTPView.as_view()),
    path('profile/', ProfileView.as_view(), name='profile'),
    path('refresh/', RefreshTokenView.as_view(), name='token-refresh'),
]