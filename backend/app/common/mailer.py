import smtplib
from email.message import EmailMessage

from app.config import settings


def send_mail(to: str, subject: str, body: str) -> None:
    """개발 환경에서는 Mailpit(http://localhost:8025)이 받는다. 실패하면 예외를 던진다."""
    msg = EmailMessage()
    msg["From"] = "no-reply@bank-ai-agent.local"
    msg["To"] = to
    msg["Subject"] = subject
    msg.set_content(body)
    with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=5) as smtp:
        smtp.send_message(msg)
