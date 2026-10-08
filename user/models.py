from django.db import models, transaction
from django.contrib.auth.models import AbstractUser
from django.contrib.auth.hashers import check_password, make_password
import uuid
from rest_framework.utils.timezone import datetime
import secrets
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
    CODE_LENGTH = 6
    MAX_FAILED_ATTEMPTS = 5
    LOCKOUT_DURATION = timedelta(minutes=15)

    user = models.OneToOneField(CustomUser, on_delete=models.CASCADE, related_name='otps')
    # This field deliberately stores a salted password hash, never the OTP itself.
    otp_code_hash = models.CharField(max_length=128, blank=True)
    otp_created_at = models.DateTimeField(auto_now_add=True)
    otp_last_generated = models.DateTimeField(default=timezone.now)
    otp_expires_at = models.DateTimeField(blank=True, null=True)
    failed_attempts = models.PositiveSmallIntegerField(default=0)
    locked_until = models.DateTimeField(blank=True, null=True)

    def __str__(self):
        return f"OTP for {self.user.email_address}"
    
    class Meta:
        ordering = ['-otp_created_at']


    def is_valid(self):
        return bool(
            self.otp_code_hash
            and self.otp_expires_at
            and self.otp_expires_at > timezone.now()
            and not self.is_locked
        )

    @property
    def is_locked(self):
        return bool(self.locked_until and self.locked_until > timezone.now())

    def generate_code(self):
        code = f"{secrets.randbelow(10 ** self.CODE_LENGTH):0{self.CODE_LENGTH}d}"
        self.otp_code_hash = make_password(code)
        self.otp_expires_at = timezone.now() + timedelta(minutes=5)
        self.otp_last_generated = timezone.now()
        self.failed_attempts = 0
        self.locked_until = None
        self.save(update_fields=[
            'otp_code_hash', 'otp_expires_at', 'otp_last_generated',
            'failed_attempts', 'locked_until',
        ])
        return code

    @classmethod
    def issue_code_for_user(cls, user, min_resend_wait=None):
        """Issue one OTP while serializing concurrent resend/generate calls."""
        with transaction.atomic():
            otp, created = cls.objects.select_for_update().get_or_create(user=user)
            now = timezone.now()

            if not created:
                if otp.is_locked:
                    return None, 'locked'
                if (
                    min_resend_wait
                    and now - otp.otp_last_generated < min_resend_wait
                ):
                    return None, 'cooldown'

            return otp.generate_code(), 'issued'

    def verify_code(self, submitted_code):
        """Atomically consume a matching OTP or record a failed attempt."""
        with transaction.atomic():
            try:
                otp = type(self).objects.select_for_update().get(pk=self.pk)
            except type(self).DoesNotExist:
                # Another request has already consumed this one-time code.
                return False

            now = timezone.now()
            if otp.is_locked:
                return False

            if (
                not otp.otp_code_hash
                or not otp.otp_expires_at
                or otp.otp_expires_at <= now
            ):
                # Expiry cleanup happens while holding the row lock, so it
                # cannot delete a newer code issued by a concurrent request.
                otp.delete()
                return False

            if check_password(submitted_code, otp.otp_code_hash):
                # Deleting inside the row-lock transaction makes the code
                # single-use even when verification requests arrive together.
                otp.delete()
                return True

            otp.failed_attempts += 1
            if otp.failed_attempts >= otp.MAX_FAILED_ATTEMPTS:
                otp.locked_until = now + otp.LOCKOUT_DURATION
            otp.save(update_fields=['failed_attempts', 'locked_until'])
            return False

    


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

