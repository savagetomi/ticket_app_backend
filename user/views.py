from rest_framework import status
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework_simplejwt.tokens import RefreshToken, AccessToken
from django.contrib.auth import authenticate
from .serializer import UserRegistrationSerializers, UserLoginSerializer, UserSerializer
from rest_framework import status
from .models import CustomUser, OTP
from datetime import timedelta
from django.utils import timezone


class RegisterView(APIView):
    permission_classes = [AllowAny]
    
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
    
    def post(self, request):

        email_address = request.data.get("email_address")
        password = request.data.get('password')

        print(email_address)
        print(password)
        print(f'Login attempt by - {email_address}')

        if not email_address or not password:
            print("Yess")
            return Response ({
                'message':'please provide both details'
            }, status=status.HTTP_401_UNAUTHORIZED)

        try:
            user_by_email = CustomUser.objects.get(email_address=email_address)
            print(f"User found by email: {user_by_email.username}")
            print(f"User is_active: {user_by_email.is_active}")
        except CustomUser.DoesNotExist:
            print("No user found with this email")
            user_by_email = None

        user = authenticate(email_address=email_address, password=password)

        print(f"Authenticate result: {user}")

        if user is not None:
            print("hiiiii")

            # if user.is_suspended:
            #     return Response({
            #         "message": "Account is Suspended",
            #         "suspension_reason": user.suspension_reason,
            #         "suspension_until": user.suspension_until,
            #     }, status=status.HTTP_403_FORBIDDEN)

            access = AccessToken.for_user(user)
            refresh = RefreshToken.for_user(user)
            print(access)
            print(refresh)
            print("Thank you Jesus")
            return Response({
                "success": True,
                "message": "User login successful",
                "access": str(access),
                "refresh": str(refresh)}, 
                status=status.HTTP_200_OK)
        else:
            print("God abeg")
            return Response({"message": "Account Not Found"}, status=status.HTTP_404_NOT_FOUND)
        
        serializer = UserLoginSerializer(data=request.data)
        # if serializer.is_valid():
        #     user = authenticate(
        #         username=serializer.validated_data['email_address'],
        #         password=serializer.validated_data['password']
        #     )
        #     if user:
        #         refresh = RefreshToken.for_user(user)
        #         return Response({
        #             'message': 'Login successful',
        #             'user': UserSerializer(user).data,
        #             'tokens': {
        #                 'refresh': str(refresh),
        #                 'access': str(refresh.access_token),
        #             }
        #         })
        #     return Response({'error': 'Invalid credentials'}, status=status.HTTP_401_UNAUTHORIZED)
        # return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


class LogoutView(APIView):
    permission_classes = [IsAuthenticated]
    
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
    
    def get(self, request):
        serializer = UserSerializer(request.user)
        return Response(serializer.data)
    
class VerifyOTPView(APIView):
    """
    Handles verification of the submitted OTP code, checking for expiration.
    """
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
            print(f"Found OTP: {otp_obj.otp_code}")

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
            # This handles cases where the email/user exists but no OTP record is found
            return Response({'message': "No pending verification found for this user.", 'success': False}, status=status.HTTP_404_NOT_FOUND)
        except CustomUser.DoesNotExist:
            # Should be caught by the OTP.DoesNotExist, but good to have as a fallback
             return Response({'message': "User not found.", 'success': False}, status=status.HTTP_404_NOT_FOUND)
        except Exception as e:
            print(f"Verification error: {e}")
            return Response({'message': "An unexpected error occurred during verification.", 'success': False}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

# class ResendOTPView(APIView):
#     def post(self, request):
#         email = request.data.get('email_address')

#         try:
#             email_add = CustomUser.objects.get(email_address=email)
#             if email_add.email_verified == False:
#                 otp_obj, created = OTP.objects.get_or_create(user=email_add)
#                 new_otp_code = otp_obj.generate_code()
#                 return Response({'message': 'OTP Sent', "success": True}, status=status.HTTP_200_OK)
#             else:
#                 return Response({'message':'Email verified', "success": False}, status=status.HTTP_400_BAD_REQUEST)
#         except CustomUser.DoesNotExist:
#             return Response({'account not found'}, status=status.HTTP_404_NOT_FOUND)

#         # --- 4. Prepare and Send NEW Email ---
        
#         subject = 'New Verification Code'
#         from_email = 'tickethub.net@gmail.com'
#         to = [user.email]

#         context = {
#             "username": user.email,
#             "description": new_otp_code,
#         }
        
#         html_content = render_to_string("otp_message.html", context)
#         text_content = f"Your new verification code is: {new_otp_code}"
        
#         msg = EmailMultiAlternatives(
#             subject=subject,
#             body=text_content, 
#             from_email=from_email,
#             to=to,
#         )
#         msg.attach_alternative(html_content, "text/html")
        
#         try:
#             msg.send()
#             return Response(
#                 {'message': "New OTP has been sent.", 'success': True}, 
#                 status=status.HTTP_200_OK
#             )
#         except Exception as e:
#             # If the email fails, we might still return success but log the error, 
#             # or return a specific error if email failure is critical.
#             print(f"Failed to resend email: {e}")
#             return Response(
#                 {'message': "OTP updated, but email send failed.", 'success': False}, 
#                 status=status.HTTP_500_INTERNAL_SERVER_ERROR
#             )
        
# users/views.py

from django.template.loader import render_to_string
from django.core.mail import EmailMultiAlternatives, send_mail

class ResendOTPView(APIView):
    """
    API endpoint to handle the resending of a verification OTP, 
    including rate limiting.
    """
    # Set the minimum wait time for clarity and easy modification
    MIN_RESEND_WAIT = timedelta(minutes=2) 
    
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

            print(f"OTP created at (DB time): {otp_obj.otp_last_generated}")
            
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
            print(f"Resending OTP: {new_otp_code}")

        except CustomUser.DoesNotExist:
            return Response(
                {'message': "User not found with this email.", 'success': False}, 
                status=status.HTTP_404_NOT_FOUND
            )
        except Exception as e:
            print(f"Error during OTP generation: {e}")
            return Response(
                {'message': f"An internal error occurred: {e}", 'success': False}, # Simplified message for user
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
        except Exception as e:
            # If the email failed, the OTP is still valid in the DB, but the user didn't get it.
            # It's safest to return a 500 here, as the user must receive the code.
            print(f"Failed to resend email: {e}")
            return Response(
                {'message': "OTP updated, but email service failed to send the message.", 'success': False}, 
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

class GenerateOTPView(APIView):
    def post(self, request):
        email = request.data.get('email_address')
        try:
            user = CustomUser.objects.get(email_address=email)

            # Create OTP
            otp_obj, _ = OTP.objects.get_or_create(user=user)
            code = otp_obj.generate_code()
            print(code)

            # Send email
            try:
                send_mail(
                    subject="Your OTP Code",
                    message=f"Your OTP is {code}",
                    from_email="dhareykhaey3@gmail.com",
                    recipient_list=[user.email_address, "dhareykhaey4@gmail.com"],
                    fail_silently=False
                )
                return Response({'message': f"OTP sent to {email}"}, status=status.HTTP_200_OK)
            except Exception as e:
                return Response({'message': f"Failed to send email: {str(e)}"}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

        except CustomUser.DoesNotExist:
            return Response({'message': 'User not found'}, status=status.HTTP_404_NOT_FOUND)