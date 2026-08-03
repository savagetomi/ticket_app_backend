import resend
from django.conf import settings

resend.api_key = settings.RESEND_API_KEY


from django.template.loader import render_to_string


def send_otp_email(user, otp_code):
    html = render_to_string(
        "user/otp_message.html",
        {
            "username": user.email_address,
            "otp_code": otp_code,
        },
    )

    resend.Emails.send({
        "from": settings.RESEND_FROM_EMAIL,
        "to": [user.email_address],
        "subject": "Verify your TicketHub account",
        "html": html,
    })

