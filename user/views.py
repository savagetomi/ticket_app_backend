import logging
from datetime import timedelta

from django.contrib.auth import authenticate
from django.core.mail import EmailMultiAlternatives, send_mail
from django.template.loader import render_to_string
from django.utils import timezone

from drf_spectacular.utils import extend_schema, OpenApiResponse, inline_serializer
from rest_framework import serializers, status
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.tokens import AccessToken, RefreshToken

from .models import CustomUser, OTP
from .serializer import UserLoginSerializer, UserRegistrationSerializers, UserSerializer

logger = logging.getLogger(__name__)


class RegisterView(APIView):
    permission_classes = [AllowAny]

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
            refresh = RefreshToken.for_user(user)
            return Response({
                'message': 'User registered successfully',
                'user': UserSerializer(user).data,
                'tokens': {
                    'refresh': str(refresh),
                    'access': str(refresh.access_token),
                }
            }, status=status.HTTP_201_CREATED)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


class LoginView(APIView):
    permission_classes = [AllowAny]

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

        if user is not None:
            access = AccessToken.for_user(user)
            refresh = RefreshToken.for_user(user)
            return Response({
                "success": True,
                "message": "User login successful",
                "access": str(access),
                "refresh": str(refresh)
            }, status=status.HTTP_200_OK)

        return Response(
            {"success": False, "message": "Invalid email or password"},
            status=status.HTTP_401_UNAUTHORIZED
        )


class LogoutView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        tags=['Authentication'],
        summary="Logout the current user",
        description="Blacklists the provided refresh token, logging the user out.",
        request=inline_serializer(
            name='LogoutRequest',
            fields={'refresh_token': serializers.CharField()}
        ),
        responses={
            200: inline_serializer(
                name='LogoutSuccessResponse',
                fields={'message': serializers.CharField()}
            ),
            400: inline_serializer(
                name='LogoutErrorResponse',
                fields={'error': serializers.CharField()}
            ),
        }
    )
    def post(self, request):
        try:
            refresh_token = request.data.get('refresh_token')
            token = RefreshToken(refresh_token)
            token.blacklist()
            return Response({'message': 'Logout successful'}, status=status.HTTP_200_OK)
        except Exception:
            return Response({'error': 'Invalid token'}, status=status.HTTP_400_BAD_REQUEST)


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


class VerifyOTPView(APIView):
    """
    Handles verification of the submitted OTP code, checking for expiration.
    """

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
        email = request.data.get('email_address')
        otp_code = request.data.get('otp_code')
        
        # 1. Input Validation
        if not email or not otp_code:
            return Response(
                {'message': "Email and OTP code are required.", 'success': False}, 
                status=status.HTTP_400_BAD_REQUEST
            )
        
        try:
            # 2. Lookup OTP object by user's email
            # We use the relationship (user__email_address) for the lookup
            otp_obj = OTP.objects.get(user__email_address=email)

            # --- CRITICAL ADDITION 1: EXPIRATION CHECK ---
            if not otp_obj.is_valid():
                otp_obj.delete() # Consume the expired code
                return Response(
                    {'message': "OTP code has expired. Please request a new one.", 'success': False}, 
                    status=status.HTTP_400_BAD_REQUEST
                )

            # --- CRITICAL ADDITION 2: CODE MATCH CHECK ---
            # Use the model's is_match if you added it, otherwise direct comparison is fine
            if otp_obj.otp_code == otp_code: 
                # SUCCESS ACTIONS
                user = otp_obj.user
                user.email_verified = True
                user.save()
                otp_obj.delete() # Consume the one-time code
                
                return Response(
                    {'message': "Successfully Verified", 'success': True}, 
                    status=status.HTTP_202_ACCEPTED
                )
            else:
                return Response(
                    {'message': "Invalid OTP", 'success': False}, 
                    status=status.HTTP_400_BAD_REQUEST
                )
            
        except OTP.DoesNotExist:
            # Covers both "no such user" and "no pending OTP" since this lookup
            # can only ever raise OTP.DoesNotExist, never CustomUser.DoesNotExist
            return Response({'message': "No pending verification found for this user.", 'success': False}, status=status.HTTP_404_NOT_FOUND)
        except Exception as e:
            logger.exception("OTP verification error")
            return Response({'message': "An unexpected error occurred during verification.", 'success': False}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


class ResendOTPView(APIView):
    """
    API endpoint to handle the resending of a verification OTP, 
    including rate limiting.
    """
    # Set the minimum wait time for clarity and easy modification
    MIN_RESEND_WAIT = timedelta(minutes=2) 

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
        
        # 1. Basic Input Check
        if not email:
            return Response(
                {'message': "Email address is required.", 'success': False}, 
                status=status.HTTP_400_BAD_REQUEST
            )

        try:
            # 2. Lookup User and OTP Object
            user = CustomUser.objects.get(email_address=email)
            otp_obj, created = OTP.objects.get_or_create(user=user)

            # Prevent resending if the user is already verified
            if user.email_verified:
                return Response(
                    {'message': "Account is already verified.", 'success': False},
                    status=status.HTTP_409_CONFLICT
                )

            # 3. CRITICAL: RATE LIMITING (Anti-Spam)
            # This logic is sound: Check if the current time minus the creation time is less than the limit.
            if not created and (timezone.now() - otp_obj.otp_last_generated) < self.MIN_RESEND_WAIT:
                wait_time_seconds = int((self.MIN_RESEND_WAIT - (timezone.now() - otp_obj.otp_last_generated)).total_seconds())
                
                # Format the wait time nicely for the user (e.g., "60 seconds")
                message = f"Please wait {wait_time_seconds} seconds before resending the code."
                if wait_time_seconds > 60:
                    message = f"Please wait {wait_time_seconds // 60} minute(s) and {wait_time_seconds % 60} seconds before resending."
                    
                return Response(
                    {'message': message, 'success': False},
                    status=status.HTTP_429_TOO_MANY_REQUESTS
                )
            
            # 4. Generate NEW Code and Expiry 
            # This uses the correct, zero-padded, time-setting method in the OTP model
            new_otp_code = otp_obj.generate_code()

        except CustomUser.DoesNotExist:
            return Response(
                {'message': "User not found with this email.", 'success': False}, 
                status=status.HTTP_404_NOT_FOUND
            )
        except Exception:
            logger.exception("Error during OTP generation")
            return Response(
                {'message': "An internal error occurred. Please try again later.", 'success': False},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

        # --- 5. Send NEW Email ---
        subject = 'New Verification Code'
        from_email = 'dhareykhaey3@gmail.com'
        
        # Use user.email_address for the recipient since that's what you used for lookup
        to = [user.email_address] 

        context = {
            # Use user.email_address for consistency, assuming this is the primary email field
            "username": user.email_address, 
            "otp_code": new_otp_code,
        }
        
        html_content = render_to_string("user/otp_message.html", context)
        text_content = f"Your new verification code is: {new_otp_code}"
        
        # Improved EmailMultiAlternatives instantiation (using keywords is clearer)
        msg = EmailMultiAlternatives(
            subject=subject, 
            body=text_content, 
            from_email=from_email, 
            to=to
        )
        msg.attach_alternative(html_content, "text/html")
        
        try:
            msg.send()
            return Response(
                {'message': "New OTP has been sent.", 'success': True}, 
                status=status.HTTP_200_OK
            )
        except Exception:
            # If the email failed, the OTP is still valid in the DB, but the user didn't get it.
            # It's safest to return a 500 here, as the user must receive the code.
            logger.exception("Failed to send resend-OTP email")
            return Response(
                {'message': "OTP updated, but email service failed to send the message.", 'success': False}, 
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )


class GenerateOTPView(APIView):

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
        email = request.data.get('email_address')
        try:
            user = CustomUser.objects.get(email_address=email)

            # Create OTP
            otp_obj, _ = OTP.objects.get_or_create(user=user)
            code = otp_obj.generate_code()

            # Send email
            try:
                send_mail(
                    subject="Your OTP Code",
                    message=f"Your OTP is {code}",
                    from_email="dhareykhaey3@gmail.com",
                    recipient_list=[user.email_address],
                    fail_silently=False
                )
                return Response({'message': f"OTP sent to {email}"}, status=status.HTTP_200_OK)
            except Exception:
                logger.exception("Failed to send OTP email")
                return Response({'message': "Failed to send email"}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

        except CustomUser.DoesNotExist:
            return Response({'message': 'User not found'}, status=status.HTTP_404_NOT_FOUND)