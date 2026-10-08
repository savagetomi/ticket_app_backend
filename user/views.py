import logging
from datetime import timedelta
from utils.email import send_otp_email

from django.contrib.auth import authenticate
from django.db import transaction

from drf_spectacular.utils import extend_schema, OpenApiResponse, inline_serializer
from rest_framework import serializers, status
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.tokens import RefreshToken
from rest_framework_simplejwt.serializers import TokenRefreshSerializer
from rest_framework_simplejwt.exceptions import TokenError
from rest_framework_simplejwt.token_blacklist.models import BlacklistedToken, OutstandingToken

from .models import CustomUser, OTP
from .serializer import UserRegistrationSerializers, UserSerializer, UserUpdateSerializer

logger = logging.getLogger(__name__)


class RegisterView(APIView):

    permission_classes = [AllowAny]
    throttle_scope = 'auth_register'

    @extend_schema(
        tags=['Authentication'],
        summary="Register a new user",
        description="Creates a new user account and returns JWT tokens for immediate authentication.",
        request=UserRegistrationSerializers,
        responses={
            201: inline_serializer(
                name='RegisterSuccessResponse',
                fields={
                    'message': serializers.CharField(),
                    'user': UserSerializer(),
                    'tokens': inline_serializer(
                        name='TokenPair',
                        fields={
                            'refresh': serializers.CharField(),
                            'access': serializers.CharField(),
                        }
                    ),
                }
            ),
            400: OpenApiResponse(description="Validation errors returned by the registration serializer"),
        }
    )
    
    def post(self, request):
        serializer = UserRegistrationSerializers(data=request.data)
        if serializer.is_valid():
            user = serializer.save()
            otp_obj, _ = OTP.objects.get_or_create(user=user)
            code = otp_obj.generate_code()

            send_otp_email(user, code)
            return Response({
                'success': True,
                'message': 'User registered successfully, Please verify your mail',
                'user': UserSerializer(user).data,
                # 'tokens': {
                #     'refresh': str(refresh),
                #     'access': str(refresh.access_token),
                # }
            }, status=status.HTTP_201_CREATED)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


class LoginView(APIView):
    permission_classes = [AllowAny]
    throttle_scope = 'auth_login'

    @extend_schema(
        tags=['Authentication'],
        summary="Login with email and password",
        description="Authenticates a user using email_address and password, returning JWT access and refresh tokens.",
        request=inline_serializer(
            name='LoginRequest',
            fields={
                'email_address': serializers.EmailField(),
                'password': serializers.CharField(style={'input_type': 'password'}),
            }
        ),
        responses={
            200: inline_serializer(
                name='LoginSuccessResponse',
                fields={
                    'success': serializers.BooleanField(),
                    'message': serializers.CharField(),
                    'access': serializers.CharField(),
                    'refresh': serializers.CharField(),
                    'role': serializers.CharField(),
                }
            ),
            400: inline_serializer(
                name='LoginMissingFieldsResponse',
                fields={'message': serializers.CharField()}
            ),
            401: inline_serializer(
                name='LoginInvalidCredentialsResponse',
                fields={'success': serializers.BooleanField(), 'message': serializers.CharField()}
            ),
        }
    )
    def post(self, request):
        email_address = request.data.get("email_address")
        password = request.data.get('password')

        if not email_address or not password:
            return Response({
                'message': 'Please provide both email address and password.'
            }, status=status.HTTP_400_BAD_REQUEST)

        user = authenticate(email_address=email_address, password=password)

        if user is None:
            return Response(
                {
                    "success": False,
                    "message": "Invalid email or password.",
                },
                status=status.HTTP_401_UNAUTHORIZED,
            )

        if not user.email_verified:
            return Response(
                {
                    "success": False,
                    "message": "Please verify your email before logging in.",
                },
                status=status.HTTP_403_FORBIDDEN,
            )
        
        refresh = RefreshToken.for_user(user)
        return Response({
            "success": True,
            "message": "User login successful",
            "email_verified": user.email_verified,
            "roles": user.roles,
            "access": str(refresh.access_token),
            "refresh": str(refresh)
        }, status=status.HTTP_200_OK)


class LogoutView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        tags=["Authentication"],
        summary="Logout the current user",
        description="Blacklists the provided refresh token, logging the user out.",
        request=inline_serializer(
            name="LogoutRequest",
            fields={
                "refresh_token": serializers.CharField()
            },
        ),
        responses={
            200: inline_serializer(
                name="LogoutSuccessResponse",
                fields={
                    "success": serializers.BooleanField(),
                    "message": serializers.CharField(),
                },
            ),
            400: inline_serializer(
                name="LogoutErrorResponse",
                fields={
                    "success": serializers.BooleanField(),
                    "message": serializers.CharField(),
                },
            ),
        },
    )
    def post(self, request):
        refresh_token = request.data.get("refresh_token")

        if not refresh_token:
            return Response(
                {
                    "success": False,
                    "message": "Refresh token is required.",
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            token = RefreshToken(refresh_token)
            # A valid refresh token is not sufficient: callers may only
            # revoke their own session, never another account's session.
            if str(token.get('user_id')) != str(request.user.pk):
                return Response(
                    {
                        "success": False,
                        "message": "Invalid or expired refresh token.",
                    },
                    status=status.HTTP_400_BAD_REQUEST,
                )
            token.blacklist()

            return Response(
                {
                    "success": True,
                    "message": "Logged out successfully.",
                },
                status=status.HTTP_200_OK,
            )

        except TokenError:
            return Response(
                {
                    "success": False,
                    "message": "Invalid or expired refresh token.",
                },
                status=status.HTTP_400_BAD_REQUEST,
            )


class ProfileView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        tags=['Authentication'],
        summary="Retrieve the authenticated user's profile",
        description="Returns the profile details of the currently authenticated user.",
        responses={200: UserSerializer}
    )
    def get(self, request):
        serializer = UserSerializer(request.user)
        return Response(serializer.data)

    @extend_schema(
        tags=['Authentication'],
        summary="Replace the authenticated user's profile",
        description="Full update — all editable fields (first_name, last_name, username, phone_number) must be provided.",
        request= UserUpdateSerializer,
        responses={
            200: inline_serializer(
                name='ProfileUpdateSuccessResponse',
                fields={'message': serializers.CharField(), 'user': UserSerializer()}
            ),
            400: OpenApiResponse(description="Validation errors"),
        }
    )
    def put(self, request):
        serializer = UserUpdateSerializer(request.user, data=request.data)
        if serializer.is_valid():
            serializer.save()
            return Response(
                {'message': 'Profile updated successfully', 'user': UserSerializer(request.user).data},
                status=status.HTTP_200_OK
            )
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    @extend_schema(
        tags=['Authentication'],
        summary="Partially update the authenticated user's profile",
        description="Partial update — only send the fields you want to change.",
        request=UserUpdateSerializer,
        responses={
            200: inline_serializer(
                name='ProfilePartialUpdateSuccessResponse',
                fields={'message': serializers.CharField(), 'user': UserSerializer()}
            ),
            400: OpenApiResponse(description="Validation errors"),
        }
    )
    def patch(self, request):
        serializer = UserUpdateSerializer(request.user, data=request.data, partial=True)
        if serializer.is_valid():
            serializer.save()
            return Response(
                {'message': 'Profile updated successfully', 'user': UserSerializer(request.user).data},
                status=status.HTTP_200_OK
            )
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    @extend_schema(
        tags=['Authentication'],
        summary="Deactivate the authenticated user's account",
        description="Requires the user's current password as confirmation. Deactivates the account (is_active=False) and blacklists all of the user's outstanding refresh tokens, rather than hard-deleting the row.",
        request=inline_serializer(
            name='DeleteAccountRequest',
            fields={'password': serializers.CharField(style={'input_type': 'password'})}
        ),
        responses={
            200: inline_serializer(
                name='DeleteAccountSuccessResponse',
                fields={'message': serializers.CharField()}
            ),
            400: inline_serializer(
                name='DeleteAccountMissingPasswordResponse',
                fields={'message': serializers.CharField()}
            ),
            401: inline_serializer(
                name='DeleteAccountWrongPasswordResponse',
                fields={'message': serializers.CharField()}
            ),
        }
    )
    def delete(self, request):
        password = request.data.get('password')

        if not password:
            return Response(
                {'message': 'Please confirm your password to delete your account.'},
                status=status.HTTP_400_BAD_REQUEST
            )

        if not request.user.check_password(password):
            return Response(
                {'message': 'Incorrect password.'},
                status=status.HTTP_401_UNAUTHORIZED
            )

        # Revoke every outstanding refresh token so old sessions can't refresh
        # their way back to a live access token after deactivation.
        with transaction.atomic():
            for token in OutstandingToken.objects.filter(user=request.user):
                BlacklistedToken.objects.get_or_create(token=token)

            request.user.is_active = False
            request.user.save(update_fields=['is_active'])

        return Response({'message': 'Account deactivated successfully'}, status=status.HTTP_200_OK)


class VerifyOTPView(APIView):
    """
    Handles verification of the submitted OTP code, checking for expiration.
    """
    throttle_scope = 'otp_verify'

    @extend_schema(
        tags=['OTP'],
        summary="Verify an OTP code",
        description="Validates a submitted OTP code against the stored code for the given email, checking expiration.",
        request=inline_serializer(
            name='VerifyOTPRequest',
            fields={
                'email_address': serializers.EmailField(),
                'otp_code': serializers.CharField(),
            }
        ),
        responses={
            202: inline_serializer(
                name='VerifyOTPSuccessResponse',
                fields={'message': serializers.CharField(), 'success': serializers.BooleanField()}
            ),
            400: inline_serializer(
                name='VerifyOTPBadRequestResponse',
                fields={'message': serializers.CharField(), 'success': serializers.BooleanField()}
            ),
            404: inline_serializer(
                name='VerifyOTPNotFoundResponse',
                fields={'message': serializers.CharField(), 'success': serializers.BooleanField()}
            ),
            500: inline_serializer(
                name='VerifyOTPServerErrorResponse',
                fields={'message': serializers.CharField(), 'success': serializers.BooleanField()}
            ),
        }
    )
    def post(self, request):



        email = request.data.get("email_address")

        otp_code = request.data.get("otp_code")



        if not email or not otp_code:

            return Response(

                {

                    "success": False,

                    "message": "Email address and OTP code are required."

                },

                status=status.HTTP_400_BAD_REQUEST,

            )



        try:

            user = CustomUser.objects.get(email_address=email)
            # Verified accounts authenticate through login, never through an
            # anonymously requested OTP. This prevents OTP issuance from
            # becoming a password-reset/account-takeover path.
            if user.email_verified:
                return Response(
                    {'success': False, 'message': 'Invalid verification request.'},
                    status=status.HTTP_400_BAD_REQUEST,
                )



        except CustomUser.DoesNotExist:
            return Response(
                {"success": False, "message": "Invalid verification request."},
                status=status.HTTP_400_BAD_REQUEST,
            )



        try:

            otp = OTP.objects.get(user=user)



        except OTP.DoesNotExist:
            return Response(
                {"success": False, "message": "Invalid verification request."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # This locks the row, handles expiry cleanup, records failures, and
        # atomically consumes a correct code. Keep the account state update in
        # the same outer transaction so a successful code cannot be consumed
        # without also marking the account verified.
        with transaction.atomic():
            if not otp.verify_code(otp_code):
                return Response(
                    {"success": False, "message": "Invalid verification request."},
                    status=status.HTTP_400_BAD_REQUEST,
                )

            user.email_verified = True
            user.save(update_fields=["email_verified"])



        # verify_code() consumed the OTP while holding its database row lock.



        # Generate JWT tokens

        refresh = RefreshToken.for_user(user)



        return Response(

            {

                "success": True,

                "message": "Email verified successfully.",

                "access": str(refresh.access_token),

                "refresh": str(refresh),

            },

            status=status.HTTP_200_OK,

        )

    
class ResendOTPView(APIView):
    """
    API endpoint to handle the resending of a verification OTP, 
    including rate limiting.
    """
    # Set the minimum wait time for clarity and easy modification
    MIN_RESEND_WAIT = timedelta(minutes=2)
    throttle_scope = 'otp_request'
    GENERIC_MESSAGE = 'If verification is required, a code has been sent.'

    @extend_schema(
        tags=['OTP'],
        summary="Resend a verification OTP",
        description="Generates and emails a new OTP code, enforcing a minimum wait time between resend requests.",
        request=inline_serializer(
            name='ResendOTPRequest',
            fields={'email_address': serializers.EmailField()}
        ),
        responses={
            200: inline_serializer(
                name='ResendOTPSuccessResponse',
                fields={'message': serializers.CharField(), 'success': serializers.BooleanField()}
            ),
            400: inline_serializer(
                name='ResendOTPBadRequestResponse',
                fields={'message': serializers.CharField(), 'success': serializers.BooleanField()}
            ),
            404: inline_serializer(
                name='ResendOTPNotFoundResponse',
                fields={'message': serializers.CharField(), 'success': serializers.BooleanField()}
            ),
            409: inline_serializer(
                name='ResendOTPConflictResponse',
                fields={'message': serializers.CharField(), 'success': serializers.BooleanField()}
            ),
            429: inline_serializer(
                name='ResendOTPRateLimitedResponse',
                fields={'message': serializers.CharField(), 'success': serializers.BooleanField()}
            ),
            500: inline_serializer(
                name='ResendOTPServerErrorResponse',
                fields={'message': serializers.CharField(), 'success': serializers.BooleanField()}
            ),
        }
    )
    def post(self, request):
        email = request.data.get('email_address')

        if not email:
            return Response(
                {'message': 'Email address is required.', 'success': False},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            user = CustomUser.objects.get(email_address=email)
            if user.email_verified:
                return Response({'message': self.GENERIC_MESSAGE, 'success': True})

            # The helper locks the one-to-one OTP row before inspecting the
            # resend window or replacing its hash. Email is sent only after
            # that transaction has committed.
            new_otp_code, outcome = OTP.issue_code_for_user(
                user, min_resend_wait=self.MIN_RESEND_WAIT
            )

        except CustomUser.DoesNotExist:
            return Response({'message': self.GENERIC_MESSAGE, 'success': True})
        except Exception:
            logger.exception('Failed to prepare resend OTP')
            return Response({'message': self.GENERIC_MESSAGE, 'success': True})

        if outcome != 'issued':
            return Response({'message': self.GENERIC_MESSAGE, 'success': True})

        try:
            send_otp_email(user, new_otp_code)
        except Exception:
            logger.exception('Failed to send resend OTP email')

        return Response({'message': self.GENERIC_MESSAGE, 'success': True})


class GenerateOTPView(APIView):

    MIN_RESEND_WAIT = timedelta(minutes=2)
    throttle_scope = 'otp_request'
    GENERIC_MESSAGE = 'If verification is required, a code has been sent.'

    @extend_schema(
        tags=['OTP'],
        summary="Generate and send an initial OTP",
        description="Creates an OTP for the given user and emails the code.",
        request=inline_serializer(
            name='GenerateOTPRequest',
            fields={'email_address': serializers.EmailField()}
        ),
        responses={
            200: inline_serializer(
                name='GenerateOTPSuccessResponse',
                fields={'message': serializers.CharField()}
            ),
            404: inline_serializer(
                name='GenerateOTPNotFoundResponse',
                fields={'message': serializers.CharField()}
            ),
            500: inline_serializer(
                name='GenerateOTPServerErrorResponse',
                fields={'message': serializers.CharField()}
            ),
        }
    )

    def post(self, request):
        email = request.data.get("email_address")

        try:
            user = CustomUser.objects.get(email_address=email)
            if user.email_verified:
                return Response({'success': True, 'message': self.GENERIC_MESSAGE})

            code, outcome = OTP.issue_code_for_user(
                user, min_resend_wait=self.MIN_RESEND_WAIT
            )
            if outcome == 'issued':
                try:
                    # issue_code_for_user has already committed its row lock.
                    send_otp_email(user, code)
                except Exception:
                    logger.exception('Failed to send generated OTP email')

            return Response({'success': True, 'message': self.GENERIC_MESSAGE})

        except CustomUser.DoesNotExist:
            return Response({'success': True, 'message': self.GENERIC_MESSAGE})

        except Exception:
            logger.exception("Failed to generate verification OTP")
            return Response({'success': True, 'message': self.GENERIC_MESSAGE})

class RefreshTokenView(APIView):
    permission_classes = [AllowAny]
    throttle_scope = 'token_refresh'

    @extend_schema(
        tags=['Authentication'],
        summary="Refresh an access token",
        description="Exchanges a valid refresh token for a new access token. If ROTATE_REFRESH_TOKENS is enabled in SIMPLE_JWT settings, a new refresh token is also returned and the old one is blacklisted.",
        request=inline_serializer(
            name='RefreshTokenRequest',
            fields={'refresh': serializers.CharField()}
        ),
        responses={
            200: inline_serializer(
                name='RefreshTokenSuccessResponse',
                fields={
                    'success': serializers.BooleanField(),
                    'access': serializers.CharField(),
                    'refresh': serializers.CharField(required=False),
                }
            ),
            400: inline_serializer(
                name='RefreshTokenMissingResponse',
                fields={'success': serializers.BooleanField(), 'message': serializers.CharField()}
            ),
            401: inline_serializer(
                name='RefreshTokenInvalidResponse',
                fields={'success': serializers.BooleanField(), 'message': serializers.CharField()}
            ),
        }
    )
    def post(self, request):
        refresh_token = request.data.get('refresh_token')

        if not refresh_token:
            return Response(
                {'success': False, 'message': 'Refresh token is required.'},
                status=status.HTTP_400_BAD_REQUEST
            )

        serializer = TokenRefreshSerializer(data={'refresh': refresh_token})

        try:
            serializer.is_valid(raise_exception=True)
        except TokenError as e:
            logger.info("Refresh token rejected: %s", e)
            return Response(
                {'success': False, 'message': 'Refresh token is invalid or expired.'},
                status=status.HTTP_401_UNAUTHORIZED
            )

        data = serializer.validated_data
        data['success'] = True
        return Response(data, status=status.HTTP_200_OK)
