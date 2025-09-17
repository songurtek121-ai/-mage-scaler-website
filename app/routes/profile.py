# app/routes/profile.py
from datetime import datetime
import json
from sqlalchemy import func
from flask import Blueprint, render_template, request, redirect, url_for, flash, abort
from flask_login import login_required, current_user

from .. import db
from ..models import AuditEvent

profile_bp = Blueprint("profile", __name__, url_prefix="/profile")

# Seviye eşikleri ve ödüller (toplam satın alınan tokene göre)
TIER_THRESHOLDS = {1: 300, 2: 750, 3: 2000}
TIER_REWARDS    = {1:  50, 2: 150, 3:  400}


def _sum_meta_tokens(query):
    """AuditEvent.meta içinden {'tokens': N} alanlarını toplayan yardımcı."""
    total = 0
    for (meta_txt,) in query:
        try:
            total += int(json.loads(meta_txt or "{}").get("tokens", 0))
        except Exception:
            pass
    return total


@profile_bp.get("/")
@login_required
def profile_page():
    u = current_user

    # ── Günlük ödül sayaçları ────────────────────────────────────────────────────
    daily_count = (
        db.session.query(func.count(AuditEvent.id))
        .filter_by(user_id=u.id, event="daily_claim")
        .scalar()
    ) or 0
    today_claimed = bool(
        getattr(u, "last_daily_claim", None)
        and u.last_daily_claim.date() == datetime.utcnow().date()
    )

    # ── Satın alınan / harcanan token toplamlari (şablona düz sayı veriyoruz) ───
    purchased_total = _sum_meta_tokens(
        db.session.query(AuditEvent.meta)
        .filter_by(user_id=u.id, event="token_purchase")
        .all()
    )

    # Not: Harcama log’unuzun ismi farklıysa burada güncelleyin (örn: 'token_spent')
    tokens_spent_total = _sum_meta_tokens(
        db.session.query(AuditEvent.meta)
        .filter_by(user_id=u.id, event="token_spent")
        .all()
    )

    # ── Seviye/ödül durumları ──────────────────────────────────────────────────
    claimed_set = set()
    for (meta_txt,) in (
        db.session.query(AuditEvent.meta)
        .filter_by(user_id=u.id, event="tier_claim")
        .all()
    ):
        try:
            t = int(json.loads(meta_txt or "{}").get("tier", 0))
            claimed_set.add(t)
        except Exception:
            pass

    eligible = {
        1: purchased_total >= TIER_THRESHOLDS[1],
        2: purchased_total >= TIER_THRESHOLDS[2],
        3: purchased_total >= TIER_THRESHOLDS[3],
    }

    # İlerleme barı için yüzde ve işaretler
    pct_total = max(0.0, min(100.0, (purchased_total / TIER_THRESHOLDS[3]) * 100.0))
    tick1 = (TIER_THRESHOLDS[1] / TIER_THRESHOLDS[3]) * 100.0  # 300 / 2000
    tick2 = (TIER_THRESHOLDS[2] / TIER_THRESHOLDS[3]) * 100.0  # 750 / 2000
    tick3 = 100.0

    # ── Siparişler (token satın alma) ve işlem geçmişi ──────────────────────────
    orders = (
        AuditEvent.query.filter_by(user_id=u.id, event="token_purchase")
        .order_by(AuditEvent.created_at.desc())
        .limit(50)
        .all()
    )
    history = (
        AuditEvent.query.filter_by(user_id=u.id)
        .order_by(AuditEvent.created_at.desc())
        .limit(50)
        .all()
    )

    def parse_meta(ev):
        try:
            return json.loads(ev.meta or "{}")
        except Exception:
            return {}

    return render_template(
        "profile.html",
        user=u,
        daily_count=daily_count,
        today_claimed=today_claimed,
        purchased_total=purchased_total,
        tokens_spent_total=tokens_spent_total,
        claimed_set=claimed_set,
        eligible=eligible,
        pct_total=pct_total,
        tick1=tick1,
        tick2=tick2,
        tick3=tick3,
        TIER_THRESHOLDS=TIER_THRESHOLDS,
        TIER_REWARDS=TIER_REWARDS,
        orders=orders,
        history=history,
        parse_meta=parse_meta,
    )


@profile_bp.post("/claim-tier/<int:tier>")
@login_required
def claim_tier(tier: int):
    if tier not in (1, 2, 3):
        abort(404)

    # Toplam satın alınan token
    purchased_total = 0
    for (meta_txt,) in (
        db.session.query(AuditEvent.meta)
        .filter_by(user_id=current_user.id, event="token_purchase")
        .all()
    ):
        try:
            purchased_total += int(json.loads(meta_txt or "{}").get("tokens", 0))
        except Exception:
            pass

    # Yeterli mi?
    if purchased_total < TIER_THRESHOLDS[tier]:
        flash("Bu ödül için gerekli eşik henüz tamamlanmadı.", "error")
        return redirect(url_for("profile.profile_page"))

    # Daha önce alınmış mı?
    already = False
    for (meta_txt,) in (
        db.session.query(AuditEvent.meta)
        .filter_by(user_id=current_user.id, event="tier_claim")
        .all()
    ):
        try:
            if int(json.loads(meta_txt or "{}").get("tier", 0)) == tier:
                already = True
                break
        except Exception:
            pass

    if already:
        flash("Bu ödülü daha önce aldınız.", "warning")
        return redirect(url_for("profile.profile_page"))

    # Token ekle ve claim kaydı yaz
    reward = TIER_REWARDS[tier]
    current_user.tokens = (current_user.tokens or 0) + reward
    db.session.add(
        AuditEvent(
            user_id=current_user.id,
            event="tier_claim",
            meta=json.dumps(
                {"tier": tier, "reward": reward, "purchased_total": purchased_total}
            ),
        )
    )
    try:
        db.session.commit()
        flash(f"{reward} token ödül eklendi.", "success")
    except Exception:
        db.session.rollback()
        flash("Ödül verilirken bir hata oluştu.", "error")

    return redirect(url_for("profile.profile_page"))
