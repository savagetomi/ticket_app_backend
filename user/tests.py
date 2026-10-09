from datetime import timedelta

from django.core.cache import cache
from django.test import Client, RequestFactory, TestCase, override_settings
from rest_framework.throttling import AnonRateThrottle
from rest_framework.test import APIClient
from rest_framework_simplejwt.token_blacklist.models import BlacklistedToken
from rest_framework_simplejwt.tokens import RefreshToken
from unittest.mock import patch

from .models import CustomUser, OTP
from .serializer import UserRegistrationSerializers


class OTPModelTests(TestCase):
    def setUp(self):
        self.user = CustomUser.objects.create_user(
            username='otp-user',
            email_address='otp@example.com',
            first_name='OTP',
            last_name='User',
            phone_number='08000000000',
            password='SafePassword123!',
        )

    def test_generated_code_is_hashed_and_verifiable(self):
        otp = OTP.objects.create(user=self.user)

        code = otp.generate_code()

        self.assertNotEqual(code, otp.otp_code_hash)
        self.assertEqual(len(code), OTP.CODE_LENGTH)
        self.assertTrue(otp.verify_code(code))
        self.assertFalse(otp.verify_code(code))

    def test_invalid_codes_lock_after_bounded_attempts(self):
        otp = OTP.objects.create(user=self.user)
        otp.generate_code()

        for _ in range(OTP.MAX_FAILED_ATTEMPTS):
            self.assertFalse(otp.verify_code('0' * OTP.CODE_LENGTH))

        otp.refresh_from_db()
        self.assertTrue(otp.is_locked)

    def test_issue_helper_enforces_the_resend_window(self):
        code, outcome = OTP.issue_code_for_user(
            self.user, min_resend_wait=timedelta(minutes=2)
        )
        second_code, second_outcome = OTP.issue_code_for_user(
            self.user, min_resend_wait=timedelta(minutes=2)
        )

        self.assertEqual(outcome, 'issued')
        self.assertTrue(code)
        self.assertIsNone(second_code)
        self.assertEqual(second_outcome, 'cooldown')


class OTPViewTests(TestCase):
    @patch('user.views.send_otp_email')
    def test_verified_account_cannot_receive_anonymous_otp(self, send_otp_email):
        user = CustomUser.objects.create_user(
            username='verified-user',
            email_address='verified@example.com',
            first_name='Verified',
            last_name='User',
            phone_number='08000000003',
            password='SafePassword123!',
            email_verified=True,
        )

        response = APIClient().post(
            '/auth/gen-otp/',
            {'email_address': user.email_address},
            format='json',
        )

        self.assertEqual(response.status_code, 200)
        self.assertFalse(OTP.objects.filter(user=user).exists())
        send_otp_email.assert_not_called()

    @patch('user.views.send_otp_email')
    def test_resend_response_does_not_reveal_account_state(self, send_otp_email):
        CustomUser.objects.create_user(
            username='verified-resend-user',
            email_address='verified-resend@example.com',
            first_name='Verified',
            last_name='Resend',
            phone_number='08000000004',
            password='SafePassword123!',
            email_verified=True,
        )
        client = APIClient()

        existing = client.post(
            '/auth/resend-otp/', {'email_address': 'verified-resend@example.com'}, format='json'
        )
        missing = client.post(
            '/auth/resend-otp/', {'email_address': 'missing@example.com'}, format='json'
        )

        self.assertEqual(existing.status_code, 200)
        self.assertEqual(missing.status_code, 200)
        self.assertEqual(existing.data, missing.data)
        send_otp_email.assert_not_called()


class SessionSecurityTests(TestCase):
    def setUp(self):
        self.user = CustomUser.objects.create_user(
            username='session-user',
            email_address='session@example.com',
            first_name='Session',
            last_name='User',
            phone_number='08000000005',
            password='SafePassword123!',
            email_verified=True,
        )
        self.other_user = CustomUser.objects.create_user(
            username='other-session-user',
            email_address='other-session@example.com',
            first_name='Other',
            last_name='User',
            phone_number='08000000006',
            password='SafePassword123!',
            email_verified=True,
        )

    def test_logout_cannot_blacklist_another_users_refresh_token(self):
        other_refresh = RefreshToken.for_user(self.other_user)
        client = APIClient()
        client.force_authenticate(self.user)

        response = client.post('/auth/logout/', {'refresh_token': str(other_refresh)}, format='json')

        self.assertEqual(response.status_code, 400)

    def test_deactivate_account_blacklists_refresh_tokens(self):
        RefreshToken.for_user(self.user)
        client = APIClient()
        client.force_authenticate(self.user)

        response = client.delete('/auth/profile/', {'password': 'SafePassword123!'}, format='json')

        self.assertEqual(response.status_code, 200)
        self.user.refresh_from_db()
        self.assertFalse(self.user.is_active)
        self.assertTrue(CustomUser.objects.filter(pk=self.user.pk).exists())
        self.assertTrue(BlacklistedToken.objects.filter(token__user=self.user).exists())


class AccountRecoveryTests(TestCase):
    def setUp(self):
        self.account = CustomUser.objects.create_user(
            username='recoverable-user',
            email_address='recoverable@example.com',
            first_name='Recoverable',
            last_name='User',
            phone_number='08000000013',
            password='SafePassword123!',
            email_verified=True,
        )
        self.regular_user = CustomUser.objects.create_user(
            username='non-admin-user',
            email_address='non-admin@example.com',
            first_name='Non',
            last_name='Admin',
            phone_number='08000000014',
            password='SafePassword123!',
            email_verified=True,
        )
        self.admin_user = CustomUser.objects.create_user(
            username='account-admin',
            email_address='account-admin@example.com',
            first_name='Account',
            last_name='Admin',
            phone_number='08000000015',
            password='SafePassword123!',
            roles='admin',
            is_staff=True,
            email_verified=True,
        )
        self.account.is_active = False
        self.account.save(update_fields=['is_active'])

    def test_deactivated_account_cannot_login_or_access_profile(self):
        login_response = APIClient().post(
            '/auth/login/',
            {
                'email_address': self.account.email_address,
                'password': 'SafePassword123!',
            },
            format='json',
        )
        profile_client = APIClient()
        profile_client.force_authenticate(self.account)
        profile_response = profile_client.get('/auth/profile/')

        self.assertEqual(login_response.status_code, 401)
        self.assertEqual(profile_response.status_code, 403)

    def test_only_account_administrator_can_inspect_and_reactivate(self):
        detail_url = f'/auth/admin/users/{self.account.pk}/'
        reactivate_url = f'/auth/admin/users/{self.account.pk}/reactivate/'
        client = APIClient()
        client.force_authenticate(self.regular_user)

        denied = client.get(detail_url)
        self.assertEqual(denied.status_code, 403)

        client.force_authenticate(self.admin_user)
        detail = client.get(detail_url)
        reactivated = client.post(reactivate_url, format='json')

        self.assertEqual(detail.status_code, 200)
        self.assertFalse(detail.data['user']['is_active'])
        self.assertNotIn('password', detail.data['user'])
        self.assertEqual(reactivated.status_code, 200)
        self.account.refresh_from_db()
        self.assertTrue(self.account.is_active)


class RegistrationRoleTests(TestCase):
    def test_registration_rejects_admin_role_but_keeps_host_enrollment(self):
        base_data = {
            'first_name': 'Role',
            'last_name': 'Test',
            'email_address': 'role@example.com',
            'username': 'role-test',
            'phone_number': '08000000007',
            'password': 'SafePassword123!',
            'confirm_password': 'SafePassword123!',
        }

        admin_serializer = UserRegistrationSerializers(data={**base_data, 'roles': 'admin'})
        host_serializer = UserRegistrationSerializers(data={**base_data, 'roles': 'host'})

        self.assertFalse(admin_serializer.is_valid())
        self.assertIn('roles', admin_serializer.errors)
        self.assertTrue(host_serializer.is_valid(), host_serializer.errors)


class RateLimitSecurityTests(TestCase):
    def tearDown(self):
        cache.clear()
        super().tearDown()

    def test_drf_uses_remote_addr_instead_of_spoofed_forwarded_for(self):
        request = RequestFactory().get(
            '/', REMOTE_ADDR='198.51.100.20', HTTP_X_FORWARDED_FOR='203.0.113.99'
        )

        self.assertEqual(AnonRateThrottle().get_ident(request), '198.51.100.20')

    @override_settings(GLOBAL_RATE_LIMIT_ANON_REQUESTS=1)
    def test_global_limiter_applies_to_non_drf_routes(self):
        cache.clear()
        client = Client()

        first = client.get('/not-a-route/', REMOTE_ADDR='198.51.100.21')
        second = client.get(
            '/not-a-route/',
            REMOTE_ADDR='198.51.100.21',
            HTTP_X_FORWARDED_FOR='203.0.113.100',
        )

        self.assertEqual(first.status_code, 404)
        self.assertEqual(second.status_code, 429)
