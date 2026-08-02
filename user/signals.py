from django.db.models.signals import post_save
from .models import CustomUser,OTP
from django.template.loader import render_to_string
from django.dispatch import receiver
from django.core.mail import send_mail, EmailMultiAlternatives



@receiver(post_save, sender=CustomUser)
def send_otp(sender, created, instance, **kwargs):


    if created:
        otp_obj = OTP.objects.create(user=instance)
        otpp = otp_obj.generate_code()
        print(otpp)

        recipient_email = instance.email_address
        print(f"{recipient_email} - recipient email")
        username = instance.email_address
        print(f"{username} - username")

        subject = 'Account Verification Required: Welcome to the Hub!'
        # message = f'Okay nah {otp_obj.otp_code}',
        from_email = 'dhareykhaey3@gmail.com'
        to = [recipient_email, "dhareykhaey4@gmail.com"]
        print(f"to - {to}")

        context = {"username": username, 'otp_code': otpp}
        html_content = render_to_string("user/otp_message.html", context)
        text_content = f"Welcome, {username}. Please use this code to verify your account: {otpp}"
        

        msg = EmailMultiAlternatives(
            subject=subject,
            body=text_content, 
            from_email=from_email,
            to=to
        )
        msg.attach_alternative(html_content, "text/html")

        try:
            msg.send()
            print("OTP Email Sent")
        except Exception as e:
            print("OTP Failed to send")
        

        # send_mail(
        #     subject = 'We dey come',
        #     message = f'Okay nah {otp_obj.otp_code}',
        #     from_email = 'tickethub.net@gmail.com',
        #     recipient_list = [instance.email]
        # )