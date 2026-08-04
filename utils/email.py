from django.conf import settings
from django.core.mail import EmailMultiAlternatives
from django.template.loader import render_to_string


def send_otp_email(user, otp_code):
    subject = "Verify your TicketHub account"

    html_content = render_to_string(
        "user/otp_message.html",
        {
            "username": user.email_address,
            "otp_code": otp_code,
        },
    )

    email = EmailMultiAlternatives(
        subject=subject,
        body=f"Your OTP is {otp_code}",
        from_email=settings.DEFAULT_FROM_EMAIL,
        to=[user.email_address],
    )

    email.attach_alternative(html_content, "text/html")
    email.send()