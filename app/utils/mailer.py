# app/utils/mailer.py
import smtplib, ssl
from email.message import EmailMessage
from flask import current_app

def send_email(subject: str, to: str, html: str, text: str | None = None):
    cfg = current_app.config
    host = cfg.get('MAIL_SERVER')
    port = int(cfg.get('MAIL_PORT', 587))
    user = cfg.get('MAIL_USERNAME')
    pwd  = cfg.get('MAIL_PASSWORD')
    from_addr = cfg.get('MAIL_DEFAULT_SENDER') or user
    use_tls = cfg.get('MAIL_USE_TLS', True)
    use_ssl = cfg.get('MAIL_USE_SSL', False)

    if not (host and user and pwd):
        raise RuntimeError("SMTP not configured")

    msg = EmailMessage()
    msg['Subject'] = subject
    msg['From'] = from_addr
    msg['To'] = to
    if text:
        msg.set_content(text)
    else:
        msg.set_content('This email requires an HTML-capable client.')
    msg.add_alternative(html, subtype='html')

    if use_ssl:
        context = ssl.create_default_context()
        with smtplib.SMTP_SSL(host, port, context=context) as server:
            server.login(user, pwd)
            server.send_message(msg)
    else:
        with smtplib.SMTP(host, port) as server:
            server.ehlo()
            if use_tls:
                server.starttls(context=ssl.create_default_context())
                server.ehlo()
            server.login(user, pwd)
            server.send_message(msg)
