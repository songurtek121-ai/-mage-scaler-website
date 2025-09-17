# app/routes/rewards.py
from datetime import datetime
import json

from flask import Blueprint, current_app, jsonify
from flask_login import login_required, current_user

from .. import db

rewards_bp = Blueprint("rewards", __name__)


@rewards_bp.post("/daily-token")
@login_required
def daily_token():
    """
    Günlük ödül (token) ver.
    - 24 saat kuralı: Kullanıcı son aldığı ödülden 24 saat geçmeden tekrar alamaz.
    - Başarılı olduğunda:
        * user.tokens artırılır
        * user.last_daily_claim = now
        * audit_event tablosuna 'daily_claim' kaydı düşülür  <-- PROFİL/ADMİN sayaçları bununla çalışır
    """
    from ..models import AuditEvent  # circular import’ı önlemek için burada

    now = datetime.utcnow()

    # 24 saat kuralı — kalan süreyi 429 ile döndür
    if current_user.last_daily_claim:
        elapsed = (now - current_user.last_daily_claim).total_seconds()
        wait = 24 * 3600 - elapsed
        if wait > 0:
            return jsonify(ok=False, remaining=int(wait)), 429

    reward = int(current_app.config.get("DAILY_REWARD_TOKENS", 1))

    try:
        # 1) Token ekle
        current_user.tokens = int(current_user.tokens or 0) + reward
        # 2) Zamanı güncelle
        current_user.last_daily_claim = now
        # 3) Audit log (profil/admin sayaçları için kritik)
        db.session.add(
            AuditEvent(
                user_id=current_user.id,
                event="daily_claim",
                created_at=now,
                meta=json.dumps({"tokens": reward}),
            )
        )
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        return jsonify(ok=False, error=str(e)), 500

    # Frontend’in sayacı hemen güncelleyebilmesi için güncel token + bir sonraki bekleme süresi
    return jsonify(ok=True, tokens=int(current_user.tokens), next_seconds=24 * 3600)


# (Opsiyonel) Kalan süreyi sadece okumak için küçük yardımcı endpoint.
@rewards_bp.get("/daily-token/status")
@login_required
def daily_status():
    now = datetime.utcnow()
    if current_user.last_daily_claim:
        elapsed = (now - current_user.last_daily_claim).total_seconds()
        wait = max(0, int(24 * 3600 - elapsed))
    else:
        wait = 0
    return jsonify(remaining=wait, tokens=int(current_user.tokens or 0))
