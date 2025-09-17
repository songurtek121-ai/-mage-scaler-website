# app/models.py
from datetime import datetime
from flask_login import UserMixin
from werkzeug.security import generate_password_hash, check_password_hash
from . import db

# -------------------------------------------------
# USER
# -------------------------------------------------
class User(UserMixin, db.Model):
    __tablename__ = "user"

    id              = db.Column(db.Integer, primary_key=True)
    email           = db.Column(db.String(255), unique=True, index=True, nullable=False)
    password_hash   = db.Column(db.String(255), nullable=False)

    tokens          = db.Column(db.Integer, default=0, nullable=False)

    # Durum / yönetim
    is_verified     = db.Column(db.Integer, default=0, nullable=False)   # 0/1
    is_admin        = db.Column(db.Integer, default=0, nullable=False)   # 0/1
    is_banned       = db.Column(db.Integer, default=0, nullable=False)   # 0/1
    is_trusted      = db.Column(db.Integer, default=0, nullable=False)   # 0/1 (şüpheli hesap filtresinden muaf tutmak için)

    # Doğrulama / günlük ödül
    verify_token    = db.Column(db.String(128), nullable=True)
    verify_sent_at  = db.Column(db.DateTime, nullable=True)
    last_daily_claim= db.Column(db.DateTime, nullable=True)

    # Zaman damgaları
    created_at      = db.Column(db.DateTime, default=datetime.utcnow, nullable=False, index=True)
    last_login_at   = db.Column(db.DateTime, nullable=True)

    # İlişkiler
    audit_events    = db.relationship("AuditEvent", backref="user", lazy=True)

    # ---- yardımcılar ----
    def set_password(self, raw: str):
        self.password_hash = generate_password_hash(raw)

    def check_password(self, raw: str) -> bool:
        try:
            return check_password_hash(self.password_hash or "", raw or "")
        except Exception:
            return False

    def __repr__(self) -> str:
        return f"<User {self.id} {self.email} tokens={self.tokens}>"

# email’i otomatik küçük harfe çevir
@db.event.listens_for(User, "before_insert")
def _user_lower_email_before_insert(mapper, connection, target: User):
    if target.email:
        target.email = target.email.strip().lower()

@db.event.listens_for(User, "before_update")
def _user_lower_email_before_update(mapper, connection, target: User):
    if target.email:
        target.email = target.email.strip().lower()


# -------------------------------------------------
# AUDIT LOG (olay günlüğü)
# -------------------------------------------------
class AuditEvent(db.Model):
    __tablename__ = "audit_event"

    id         = db.Column(db.Integer, primary_key=True)
    user_id    = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=True)
    event      = db.Column(db.String(40), nullable=False, index=True)  # örn: register, login, upload, token_spent, token_purchase, daily_claim, reward_claim, coupon_redeem
    meta       = db.Column(db.Text, nullable=True)                     # JSON string
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False, index=True)

    def __repr__(self) -> str:
        return f"<AuditEvent {self.event} uid={self.user_id} at={self.created_at}>"

# -------------------------------------------------
# COUPONS
# -------------------------------------------------
class Coupon(db.Model):
    __tablename__ = "coupon"

    id               = db.Column(db.Integer, primary_key=True)
    code             = db.Column(db.String(64), unique=True, index=True, nullable=False)  # büyük harf olarak sakla
    created_at       = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    expires_at       = db.Column(db.DateTime, nullable=True)   # None => süresiz
    max_uses         = db.Column(db.Integer, default=1, nullable=False)
    type             = db.Column(db.String(16), nullable=False)  # 'token' | 'discount'
    reward_tokens    = db.Column(db.Integer, default=0, nullable=False)  # type=='token'
    discount_percent = db.Column(db.Integer, default=0, nullable=False)  # type=='discount' (0-100)
    created_by       = db.Column(db.Integer, nullable=True)  # admin user_id (opsiyonel)

    redemptions      = db.relationship("CouponRedemption", backref="coupon", lazy=True)

    def used_count(self) -> int:
        return len(self.redemptions or [])

    def __repr__(self) -> str:
        return f"<Coupon {self.code} type={self.type}>"

@db.event.listens_for(Coupon, "before_insert")
def _coupon_normalize_code_before_insert(mapper, connection, target: 'Coupon'):
    if target.code:
        target.code = target.code.strip().upper().replace(" ", "")

@db.event.listens_for(Coupon, "before_update")
def _coupon_normalize_code_before_update(mapper, connection, target: 'Coupon'):
    if target.code:
        target.code = target.code.strip().upper().replace(" ", "")


class CouponRedemption(db.Model):
    __tablename__ = "coupon_redemption"

    id               = db.Column(db.Integer, primary_key=True)
    coupon_id        = db.Column(db.Integer, db.ForeignKey("coupon.id"), nullable=False)
    user_id          = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    redeemed_at      = db.Column(db.DateTime, default=datetime.utcnow, nullable=False, index=True)
    benefit_tokens   = db.Column(db.Integer, default=0, nullable=False)
    discount_percent = db.Column(db.Integer, default=0, nullable=False)

    user             = db.relationship("User", lazy=True)

    def __repr__(self) -> str:
        return f"<CouponRedemption coupon={self.coupon_id} user={self.user_id}>"
