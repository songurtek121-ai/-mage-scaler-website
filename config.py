# config.py
import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent

# Flask
SECRET_KEY = os.getenv('SECRET_KEY', 'dev-change-this')
PREFERRED_URL_SCHEME = os.getenv('PREFERRED_URL_SCHEME', 'http')
# SERVER_NAME = 'picturescaler.com'

# DB (SQLite)
SQLALCHEMY_DATABASE_URI = 'sqlite:///' + str((BASE_DIR / 'app.db')).replace('\\', '/')
SQLALCHEMY_TRACK_MODIFICATIONS = False

# Upload limit
MAX_CONTENT_LENGTH = 100 * 1024 * 1024
UPLOADS_DIRNAME = 'uploads'
OUTPUTS_DIRNAME = 'outputs'

# Test modu: e-posta doğrulaması zorunlu mu?
EMAIL_VERIFICATION_REQUIRED = os.getenv('REQUIRE_EMAIL_VERIFICATION', '0') == '1'

# SMTP
MAIL_ENABLED = os.getenv('MAIL_ENABLED', '1') == '1'
MAIL_SERVER = os.getenv('SMTP_HOST', 'smtp.gmail.com')
MAIL_PORT = int(os.getenv('SMTP_PORT', '587'))
MAIL_USERNAME = os.getenv('SMTP_USER')
MAIL_PASSWORD = os.getenv('SMTP_PASS')
MAIL_USE_TLS = os.getenv('SMTP_TLS', '1') == '1'
MAIL_USE_SSL = os.getenv('SMTP_SSL', '0') == '1'
MAIL_DEFAULT_SENDER = os.getenv('SMTP_FROM') or MAIL_USERNAME

# ---- yalnızca adminler görsün ----
# Birden çok e-postayı virgül ile ayır: "sen@x.com, digeri@y.com"
ADMIN_EMAILS = [e.strip().lower() for e in os.getenv('ADMIN_EMAILS', '').split(',') if e.strip()]
