"""Envoi d'e-mails via SMTP. Sans configuration SMTP, l'erreur est explicite (pas de faux envoi)."""
import asyncio, smtplib
from email.message import EmailMessage
from app.core.config import get_settings


class MailNotConfigured(RuntimeError):
    pass


def _send(to: str, subject: str, body: str) -> None:
    s = get_settings()
    msg = EmailMessage()
    msg["From"], msg["To"], msg["Subject"] = s.smtp_from, to, subject
    msg.set_content(body)
    with smtplib.SMTP(s.smtp_host, s.smtp_port, timeout=15) as smtp:
        smtp.starttls()
        if s.smtp_user:
            smtp.login(s.smtp_user, s.smtp_password)
        smtp.send_message(msg)


async def send_mail(to: str, subject: str, body: str) -> None:
    if not get_settings().smtp_host:
        raise MailNotConfigured("SMTP_HOST n'est pas configuré")
    await asyncio.to_thread(_send, to, subject, body)
