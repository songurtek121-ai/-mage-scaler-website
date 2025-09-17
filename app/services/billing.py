# app/services/billing.py
import json
from typing import Optional, Tuple
from sqlalchemy import text
from .. import db
from ..models import User, AuditEvent

def grant_tokens(
    user: User,
    tokens: int,
    *,
    provider: str = "manual",
    amount: Optional[float] = None,
    currency: str = "TRY",
    order_id: Optional[str] = None,  # sizin sipariş numaranız
    txn_id: Optional[str] = None     # ödeme sağlayıcının işlem id'si
) -> Tuple[bool, str]:
    """
    ÖDEME BAŞARILI OLDUĞU AN çağır.
    - Kullanıcıya 'tokens' kadar jeton ekler
    - AuditEvent'e token_purchase olayı yazar
    - order_id/txn_id aynı gelirse ikinci kez yazmaz (idempotent)
    """
    if not user or not isinstance(tokens, int) or tokens <= 0:
        return False, "Geçersiz parametre"

    # Idempotency (aynı siparişi ikinci kez işlemeyelim)
    if order_id or txn_id:
        rows = db.session.execute(
            text("""
                SELECT id, meta FROM audit_event
                WHERE event='token_purchase' AND user_id=:uid
                ORDER BY id DESC LIMIT 200
            """),
            {"uid": user.id},
        ).fetchall()
        for _, meta_txt in rows:
            try:
                m = json.loads(meta_txt or "{}")
            except Exception:
                m = {}
            if order_id and m.get("order_id") == order_id:
                return True, "Bu sipariş zaten işlenmiş (order_id eşleşti)."
            if txn_id and m.get("txn_id") == txn_id:
                return True, "Bu işlem zaten işlenmiş (txn_id eşleşti)."

    # Token ekle
    user.tokens = int(user.tokens or 0) + tokens

    # Log yaz
    meta = {
        "tokens": tokens,
        "currency": currency,
        "amount": amount,
        "provider": provider,
        "order_id": order_id,
        "txn_id": txn_id,
    }
    db.session.add(AuditEvent(user_id=user.id, event="token_purchase", meta=json.dumps(meta)))

    try:
        db.session.commit()
        return True, "Token eklendi ve satın alma loglandı."
    except Exception as e:
        db.session.rollback()
        return False, f"DB hatası: {e}"
