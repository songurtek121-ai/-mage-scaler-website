# app/routes/auth.py
import re, secrets, json
from datetime import datetime
from flask import Blueprint, render_template, request, redirect, url_for, flash, current_app
from flask_login import login_user, logout_user, login_required, current_user
from werkzeug.security import generate_password_hash, check_password_hash
from ..models import User, AuditEvent
from .. import db

auth_bp = Blueprint('auth', __name__)

EMAIL_RE = re.compile(r"^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}$")

def normalize_email(email: str) -> str:
    email = (email or '').strip().lower()
    if '@' not in email:
        return email
    local, domain = email.split('@', 1)
    if domain == 'gmail.com':
        local = local.split('+', 1)[0]
        local = local.replace('.', '')
    return f"{local}@{domain}"

def validate_password(pw: str):
    if not pw or len(pw) < 8:
        return False, "Şifre en az 8 karakter olmalı."
    if not re.search(r'[A-Z]', pw):
        return False, "Şifre en az bir büyük harf içermeli."
    if not re.search(r'[a-z]', pw):
        return False, "Şifre en az bir küçük harf içermeli."
    if not re.search(r'\d', pw):
        return False, "Şifre en az bir rakam içermeli."
    return True, None

@auth_bp.get('/login')
def login_page():
    if current_user.is_authenticated:
        return redirect(url_for('main.index'))
    return render_template('login.html')

@auth_bp.post('/login')
def login_post():
    email_raw = (request.form.get('email') or '').strip()
    password = request.form.get('password') or ''
    email = normalize_email(email_raw)

    user = User.query.filter_by(email=email).first()
    if not user or not check_password_hash(user.password_hash, password):
        flash('E-posta veya şifre hatalı', 'error')
        return redirect(url_for('auth.login_page', next=request.args.get('next')))

    require_verify = current_app.config.get('EMAIL_VERIFICATION_REQUIRED', False)
    if require_verify and not user.is_verified:
        flash('Hesabını kullanmadan önce e-posta doğrulaması yapmalısın. Gelen kutunu ve spam klasörünü kontrol et.', 'error')
        resend_url = url_for('auth.resend_verification', email=email)
        flash(f'E-posta gelmediyse buradan yeniden isteyebilirsin: {resend_url}', 'success')
        return redirect(url_for('auth.login_page'))

    login_user(user)
    # ---- LOG: login ----
    try:
        db.session.add(AuditEvent(user_id=user.id, event='login'))
        db.session.commit()
    except Exception:
        db.session.rollback()

    # Admin şablonu için otomatik yetki (ENV listesinde ise)
    try:
        admin_list = set(current_app.config.get('ADMIN_EMAILS') or [])
        if user.email.lower() in admin_list and not user.is_admin:
            user.is_admin = True
            db.session.commit()
    except Exception:
        db.session.rollback()

    flash('Hoş geldin!', 'success')
    next_url = request.args.get('next')
    return redirect(next_url or url_for('main.index'))

@auth_bp.get('/register')
def register_page():
    if current_user.is_authenticated:
        return redirect(url_for('main.index'))
    return render_template('register.html')

@auth_bp.post('/register')
def register_post():
    from ..utils.mailer import send_email

    email_input = (request.form.get('email') or '').strip()
    password = request.form.get('password') or ''

    if not EMAIL_RE.match(email_input):
        flash('Geçerli bir e-posta adresi girin.', 'error')
        return redirect(url_for('auth.register_page'))

    ok, msg = validate_password(password)
    if not ok:
        flash(msg, 'error')
        return redirect(url_for('auth.register_page'))

    email = normalize_email(email_input)
    if User.query.filter_by(email=email).first():
        flash('Bu e-posta zaten kayıtlı.', 'error')
        return redirect(url_for('auth.register_page'))

    require_verify = current_app.config.get('EMAIL_VERIFICATION_REQUIRED', False)

    token = secrets.token_urlsafe(32) if require_verify else None
    user = User(
        email=email,
        password_hash=generate_password_hash(password),
        tokens=3,
        is_verified=(not require_verify),
        verify_token=token,
        verify_sent_at=datetime.utcnow() if require_verify else None,
    )
    db.session.add(user)
    db.session.commit()

    # ---- LOG: register ----
    try:
        db.session.add(AuditEvent(user_id=user.id, event='register'))
        db.session.commit()
    except Exception:
        db.session.rollback()

    if require_verify:
        verify_url = url_for('auth.verify_email', token=token, _external=True)
        sent = False
        if current_app.config.get('MAIL_ENABLED') and current_app.config.get('MAIL_USERNAME') and current_app.config.get('MAIL_PASSWORD'):
            html = render_template('email/verify.html', verify_url=verify_url, email=email)
            text = render_template('email/verify.txt', verify_url=verify_url, email=email)
            try:
                send_email(subject="PictureScaler | E-posta Doğrulama", to=email, html=html, text=text)
                sent = True
            except Exception as e:
                current_app.logger.error("Mail gönderimi başarısız: %s", e)
        return render_template('verify_sent.html', email=email, sent=sent)

    flash('Kayıt tamamlandı. Giriş yapabilirsiniz.', 'success')
    return redirect(url_for('auth.login_page'))

@auth_bp.get('/verify')
def verify_email():
    token = (request.args.get('token') or '').strip()
    if not token:
        return render_template('verify_result.html', ok=False, message='Geçersiz bağlantı.')

    user = User.query.filter_by(verify_token=token).first()
    if not user:
        return render_template('verify_result.html', ok=False, message='Doğrulama bağlantısı geçersiz veya kullanılmış.')

    user.is_verified = True
    user.verify_token = None
    db.session.commit()
    return render_template('verify_result.html', ok=True, message='E-posta doğrulandı. Artık giriş yapabilirsiniz.')

@auth_bp.get('/resend-verification')
def resend_verification():
    require_verify = current_app.config.get('EMAIL_VERIFICATION_REQUIRED', False)
    if not require_verify:
        flash('Doğrulama şu anda devre dışı (test modu).', 'success')
        return redirect(url_for('auth.login_page'))

    from ..utils.mailer import send_email

    email_input = (request.args.get('email') or '').strip()
    email = normalize_email(email_input)
    user = User.query.filter_by(email=email).first()
    if not user:
        flash('Bu e-posta ile kullanıcı bulunamadı.', 'error')
        return redirect(url_for('auth.login_page'))
    if user.is_verified:
        flash('E-posta zaten doğrulanmış. Giriş yapabilirsiniz.', 'success')
        return redirect(url_for('auth.login_page'))

    token = secrets.token_urlsafe(32)
    user.verify_token = token
    user.verify_sent_at = datetime.utcnow()
    db.session.commit()

    verify_url = url_for('auth.verify_email', token=token, _external=True)

    sent = False
    if current_app.config.get('MAIL_ENABLED') and current_app.config.get('MAIL_USERNAME') and current_app.config.get('MAIL_PASSWORD'):
        html = render_template('email/verify.html', verify_url=verify_url, email=email)
        text = render_template('email/verify.txt', verify_url=verify_url, email=email)
        try:
            send_email(subject="PictureScaler | E-posta Doğrulama", to=email, html=html, text=text)
            sent = True
        except Exception as e:
            current_app.logger.error("Mail gönderimi başarısız: %s", e)

    return render_template('verify_sent.html', email=email, sent=sent)

@auth_bp.get('/logout')
@login_required
def logout():
    logout_user()
    flash('Çıkış yapıldı.', 'success')
    return redirect(url_for('main.index'))
