# app/routes/payments.py
from flask import Blueprint, request, redirect, url_for, flash
from flask_login import login_required, current_user
from ..models import User
from ..services.billing import grant_tokens

payments_bp = Blueprint('payments', __name__, url_prefix='/payments')

@payments_bp.route('/success', methods=['GET', 'POST'])
@login_required
def payment_success():
    """
    Örnek başarı dönüşü (redirect veya form post):
      /payments/success?tokens=20&amount=99.90&provider=manual&order_id=ORD123&txn_id=T123
    Gerçekte burada sağlayıcı imzasını/doğrulamasını yapmalısın; örnek basit tutuldu.
    """
    try:
        tokens = int(request.values.get('tokens') or 0)
        amount = float(request.values.get('amount') or 0)
    except Exception:
        flash("Geçersiz parametre.", "error")
        return redirect(url_for('main.index'))

    order_id = (request.values.get('order_id') or '').strip() or None
    txn_id   = (request.values.get('txn_id')   or '').strip() or None
    provider = (request.values.get('provider') or 'manual').strip()

    # TODO: Burada ödeme sağlayıcısından gelen imza/secret doğrulamasını yapmalısın.

    ok, msg = grant_tokens(
        current_user,
        tokens=tokens,
        provider=provider,
        amount=amount,
        currency="TRY",
        order_id=order_id,
        txn_id=txn_id
    )
    flash(msg, "success" if ok else "error")
    return redirect(url_for('main.index'))

@payments_bp.post('/webhook/stripe')
def stripe_webhook():
    """
    ÖRNEK şablon (tam entegrasyon değil):
    1) Header imzasını doğrula (Stripe kütüphanesi ile)
    2) Payload'dan user_id, tokens, amount, order_id/txn_id çıkar
    3) Kullanıcıyı DB'den bul ve grant_tokens(...) çağır
    """
    payload = request.get_json(silent=True) or {}
    user_id  = int(payload.get('user_id') or 0)
    tokens   = int(payload.get('tokens') or 0)
    amount   = float(payload.get('amount') or 0.0)
    order_id = str(payload.get('order_id') or '') or None
    txn_id   = str(payload.get('stripe_payment_intent_id') or '') or None

    if not (user_id and tokens > 0):
        return ('bad request', 400)

    user = User.query.get(user_id)
    if not user:
        return ('user not found', 404)

    ok, _ = grant_tokens(
        user,
        tokens=tokens,
        provider='stripe',
        amount=amount,
        currency='TRY',
        order_id=order_id,
        txn_id=txn_id
    )
    return ('ok', 200 if ok else 500)
