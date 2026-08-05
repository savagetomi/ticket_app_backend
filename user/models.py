from django.db import models
from django.contrib.auth.models import AbstractUser
import uuid
from rest_framework.utils.timezone import datetime
import random
from django.utils import timezone
from datetime import timedelta

# Create your models here.
class CustomUser(AbstractUser):
    USER_ROLES = (
        ('user', 'User'),
        ('host', 'Host'),
        ('admin', 'Admin')
    )
    id = models.UUIDField(default=uuid.uuid4, unique=True, editable=False, primary_key=True)
    first_name = models.CharField(max_length=255, blank=False)
    last_name = models.CharField(max_length=255, blank=False)
    email_address = models.CharField(max_length=255, blank=False, unique=True)
    phone_number = models.CharField(max_length=255, blank=False)
    roles = models.CharField(max_length=10, choices=USER_ROLES, default='user')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    username = models.CharField(max_length=255, unique=True, blank=True)


    # Location fields
    ip_address = models.GenericIPAddressField(blank=True, null=True)
    city = models.CharField(max_length=100, blank=True, null=True)
    country = models.CharField(max_length=100, blank=True, null=True)
    latitude = models.FloatField(blank=True, null=True)
    longitude = models.FloatField(blank=True, null=True)

    # verification
    email_verified = models.BooleanField(default=False)

    #verification otp
    # email_otp = models.CharField(max_length=4,blank=False, unique=True)
    # email_otp_created_at = models.DateTimeField(auto_now_add=True)

    USERNAME_FIELD = "email_address"
    REQUIRED_FIELDS = []

    def __str__(self):
        return self.email_address


class OTP(models.Model):
    user = models.OneToOneField(CustomUser, on_delete=models.CASCADE, related_name='otps')
    otp_code = models.CharField(max_length=4,blank=False, unique=True)
    otp_created_at = models.DateTimeField(auto_now_add=True)
    otp_last_generated = models.DateTimeField(default=timezone.now)
    otp_expires_at = models.DateTimeField(blank=True, null=True)

    def __str__(self):
        return f"Your OTP Code for {self.user.email_address} is {self.otp_code}"
    
    class Meta:
        ordering = ['-otp_created_at']


    def is_valid(self):
        # Returns True only if otp_expires_at is NOT None AND is in the future.
        return bool(self.otp_expires_at and self.otp_expires_at > timezone.now())

        

    def generate_code(self):
        self.otp_code = str(random.randint(1000, 9999))
        self.otp_expires_at = timezone.now() + timedelta(minutes=5)
        self.otp_last_generated = timezone.now()
        print(self.otp_code)
        self.save()
        return self.otp_code

    


class UserSession(models.Model):
    user = models.ForeignKey(CustomUser, on_delete=models.CASCADE)
    session_key = models.CharField(max_length=40)
    ip_address = models.GenericIPAddressField()
    user_agent = models.TextField(blank=True, null=True)
    location_data = models.JSONField(blank=True, null=True)
    login_at = models.DateTimeField(auto_now_add=True)
    logout_at = models.DateTimeField(blank=True, null=True)
    is_active = models.BooleanField(default=True)
    
    class Meta:
        db_table = 'user_sessions'

