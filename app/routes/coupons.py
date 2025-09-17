# app/routes/coupons.py
from datetime import datetime, timedelta
from flask import Blueprint, request, jsonify, current_app, abort, render_template, redirect, url_for, flash
from flask_login import login_required, current_user
from sqlalchemy import func
from .. import db
from ..models import Coupon, CouponRedemption
from .admin import _is_admin  # admin kontrolü için
from ..models import AuditEvent

coupons_bp = Blueprint('coupons', __name__)

# --- Yardımcılar ------------------------------------------------------------

def _normalize_code(code: str) -> str:
    return (code or '').strip().upper().replace(' ', '')

def _now():
    return datetime.utcnow()

# --- Kullanıcı: kupon kullan ------------------------------------------------
@coupons_bp.post('/coupon/redeem')
@login_required
def redeem_coupon():
    code = _normalize_code(request.form.get('code') or '')
    if not code:
        return jsonify(ok=False, error="Kupon kodu gerekli."), 400

    c = Coupon.query.filter(func.upper(Coupon.code) == code).first()
    if not c:
        return jsonify(ok=False, error="Kupon bulunamadı."), 404

    # banlı kullanıcılar kullanamasın
    if getattr(current_user, 'is_banned', 0):
        return jsonify(ok=False, error="Hesabınız kısıtlı."), 403

    # süresi / kullanım hakkı
    if c.expires_at and _now() > c.expires_at:
        return jsonify(ok=False, error="Kupon süresi bitmiş."), 410

    used_total = CouponRedemption.query.filter_by(coupon_id=c.id).count()
    if used_total >= c.max_uses:
        return jsonify(ok=False, error="Kupon kullanım sınırına ulaşılmış."), 409

    # aynı kullanıcı tekrar kullanamasın
    already = CouponRedemption.query.filter_by(coupon_id=c.id, user_id=current_user.id).first()
    if already:
        return jsonify(ok=False, error="Bu kuponu zaten kullandınız."), 409

    tokens_added = 0
    discount_percent = 0

    if c.type == 'token':
        tokens_added = max(0, int(c.reward_tokens or 0))
        current_user.tokens = int(current_user.tokens or 0) + tokens_added
    elif c.type == 'discount':
        discount_percent = max(0, min(100, int(c.discount_percent or 0)))
        # Şimdilik anında indirim uygulamıyoruz; bir kredi de yaratmıyoruz.
        # Sadece "kupon kullanıldı" olarak logluyoruz (satın alma akışında kontrol edilecek).
    else:
        return jsonify(ok=False, error="Geçersiz kupon tipi."), 400

    red = CouponRedemption(
        coupon_id=c.id, user_id=current_user.id,
        benefit_tokens=tokens_added, discount_percent=discount_percent
    )
    db.session.add(red)

    # Audit log
    db.session.add(AuditEvent(
        user_id=current_user.id,
        event='coupon_redeem',
        meta=f'{{"code":"{c.code}","type":"{c.type}","tokens":{tokens_added},"discount":{discount_percent}}}'
    ))
    if tokens_added > 0:
        db.session.add(AuditEvent(
            user_id=current_user.id,
            event='reward_claim',
            meta=f'{{"source":"coupon","code":"{c.code}","tokens":{tokens_added}}}'
        ))

    try:
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        return jsonify(ok=False, error=f"Hata: {e}"), 500

    return jsonify(ok=True, tokens_added=tokens_added, discount_percent=discount_percent,
                   message=("Token eklendi." if tokens_added else "İndirim kuponu kaydedildi."))

# --- Admin: kupon listesi / oluşturma --------------------------------------
@coupons_bp.get('/admin/coupons')
@login_required
def coupons_page():
    if not _is_admin():
        abort(403)

    now = _now()
    active = (Coupon.query
              .filter((Coupon.expires_at.is_(None)) | (Coupon.expires_at > now))
              .order_by(Coupon.created_at.desc())
              .all())
    expired = (Coupon.query
               .filter(Coupon.expires_at.isnot(None), Coupon.expires_at <= now)
               .order_by(Coupon.expires_at.desc())
               .all())

    # kullanılmışlar (son 200)
    used = (db.session.query(CouponRedemption, Coupon)
            .join(Coupon, Coupon.id == CouponRedemption.coupon_id)
            .order_by(CouponRedemption.redeemed_at.desc())
            .limit(200)
            .all())

    # her kupon için kullanılmış/kalan hesapla
    def usage_info(c: Coupon):
        used_count = CouponRedemption.query.filter_by(coupon_id=c.id).count()
        left = max(0, int(c.max_uses or 0) - used_count)
        return used_count, left

    usage = {c.id: usage_info(c) for c in active + expired}

    return render_template('admin_coupons.html',
                           active=active, expired=expired, used=used, usage=usage, now=now)

@coupons_bp.post('/admin/coupons/create')
@login_required
def coupons_create():
    if not _is_admin():
        abort(403)

    code = _normalize_code(request.form.get('code') or '')
    days = int(request.form.get('days') or 0)
    max_uses = max(1, int(request.form.get('max_uses') or 1))
    ctype = (request.form.get('ctype') or 'token').strip()
    reward_tokens = int(request.form.get('reward_tokens') or 0)
    discount_percent = int(request.form.get('discount_percent') or 0)

    if not code:
        flash("Kod gerekli.", "error")
        return redirect(url_for('coupons.coupons_page'))

    # kod benzersiz olsun
    exists = Coupon.query.filter(func.upper(Coupon.code) == code).first()
    if exists:
        flash("Bu kod zaten var.", "error")
        return redirect(url_for('coupons.coupons_page'))

    if ctype not in ('token', 'discount'):
        flash("Kupon tipi geçersiz.", "error")
        return redirect(url_for('coupons.coupons_page'))

    if ctype == 'token' and reward_tokens <= 0:
        flash("Ödül token miktarı > 0 olmalı.", "error")
        return redirect(url_for('coupons.coupons_page'))

    if ctype == 'discount':
        if discount_percent <= 0 or discount_percent > 100:
            flash("İndirim yüzdesi 1-100 arası olmalı.", "error")
            return redirect(url_for('coupons.coupons_page'))

    exp = None
    if days > 0:
        exp = _now() + timedelta(days=days)

    c = Coupon(
        code=code,
        expires_at=exp,
        max_uses=max_uses,
        type=ctype,
        reward_tokens=(reward_tokens if ctype == 'token' else 0),
        discount_percent=(discount_percent if ctype == 'discount' else 0),
        created_by=getattr(current_user, 'id', None)
    )
    db.session.add(c)

    # audit
    db.session.add(AuditEvent(
        user_id=getattr(current_user, 'id', None),
        event='coupon_create',
        meta=f'{{"code":"{code}","type":"{ctype}","max_uses":{max_uses},"days":{days},"reward_tokens":{reward_tokens},"discount_percent":{discount_percent}}}'
    ))

    try:
        db.session.commit()
        flash("Kupon oluşturuldu.", "success")
    except Exception as e:
        db.session.rollback()
        flash(f"Hata: {e}", "error")

    return redirect(url_for('coupons.coupons_page'))
