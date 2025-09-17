# app/routes/admin.py
from datetime import datetime, timedelta
import json, random
from flask import Blueprint, current_app, render_template, jsonify, request, abort, redirect, url_for, flash
from flask_login import login_required, current_user
from sqlalchemy import text
from .. import db
from ..models import User, AuditEvent  # kullanıcı ve log modeli

admin_bp = Blueprint('admin', __name__, url_prefix='/admin')


# --- yetki kontrolü ----------------------------------------------------------
def _is_admin():
    if not current_user.is_authenticated:
        return False
    # explicit flag
    if getattr(current_user, 'is_admin', False):
        return True
    # .env/config üzerinden tanımlı admin mailleri
    allowed = set(current_app.config.get('ADMIN_EMAILS') or [])
    return (current_user.email or '').lower() in allowed


@admin_bp.before_request
def _guard():
    if not _is_admin():
        abort(403)


# ---------------------------------------------------------------------------
# KULLANICI LİSTESİ (+ ŞÜPHELİLER / BANLILAR FİLTRESİ, ARAMA, SIRALAMA)
@admin_bp.get('/users')
@login_required
def users_page():
    """
    Görünümler:
      /admin/users?view=all|sus|banned&q=...&sort=created_desc
    Sıralamalar: email_asc/desc, tokens_asc/desc, spent_asc/desc,
                 purchased_asc/desc, claims_asc/desc, reward_asc/desc,
                 created_asc/desc
    """
    q = (request.args.get('q') or '').strip()
    sort = (request.args.get('sort') or 'created_desc').strip()
    view = (request.args.get('view') or 'all').strip()

    where = "1=1"
    params = {}
    if q:
        where = "(LOWER(u.email) LIKE LOWER(:q))"
        params['q'] = f"%{q}%"

    # harcanan & satın alınan & günlük ödül & reward kolonlarını topluyoruz
    sql = f"""
    WITH
    spent AS (
        SELECT user_id, SUM(CAST(json_extract(meta,'$.tokens') AS INTEGER)) AS spent
        FROM audit_event
        WHERE event='token_spent'
        GROUP BY user_id
    ),
    purchased AS (
        SELECT user_id, SUM(CAST(json_extract(meta,'$.tokens') AS INTEGER)) AS purchased
        FROM audit_event
        WHERE event='token_purchase'
        GROUP BY user_id
    ),
    claims AS (
        SELECT user_id, COUNT(*) AS claims
        FROM audit_event
        WHERE event='daily_claim'
        GROUP BY user_id
    ),
    rewards AS (
        SELECT user_id, SUM(CAST(json_extract(meta,'$.tokens') AS INTEGER)) AS reward
        FROM audit_event
        WHERE event='reward_claim'
        GROUP BY user_id
    )
    SELECT
        u.id, u.email, u.tokens,
        COALESCE(s.spent,0)     AS spent,
        COALESCE(p.purchased,0) AS purchased,
        COALESCE(c.claims,0)    AS claims,
        COALESCE(r.reward,0)    AS reward,
        u.is_banned             AS is_banned,
        u.is_trusted            AS is_trusted,
        u.created_at            AS created
    FROM user u
    LEFT JOIN spent     s ON s.user_id = u.id
    LEFT JOIN purchased p ON p.user_id = u.id
    LEFT JOIN claims    c ON c.user_id = u.id
    LEFT JOIN rewards   r ON r.user_id = u.id
    WHERE {where}
    """

    order_by = {
        'email_asc':        "ORDER BY LOWER(u.email) ASC",
        'email_desc':       "ORDER BY LOWER(u.email) DESC",
        'tokens_asc':       "ORDER BY u.tokens ASC",
        'tokens_desc':      "ORDER BY u.tokens DESC",
        'spent_asc':        "ORDER BY spent ASC",
        'spent_desc':       "ORDER BY spent DESC",
        'purchased_asc':    "ORDER BY purchased ASC",
        'purchased_desc':   "ORDER BY purchased DESC",
        'claims_asc':       "ORDER BY claims ASC",
        'claims_desc':      "ORDER BY claims DESC",
        'reward_asc':       "ORDER BY reward ASC",
        'reward_desc':      "ORDER BY reward DESC",
        'created_asc':      "ORDER BY created ASC",
        'created_desc':     "ORDER BY created DESC",
    }.get(sort, "ORDER BY created DESC")

    rows_raw = db.session.execute(text(sql + " " + order_by), params).fetchall()

    # ŞÜPHELİ kuralı: spent > (3 + claims + reward + purchased)  ve is_trusted=0
    def suspicious_of(r):
        free = 3 + int(r.claims or 0) + int(r.reward or 0)
        limit = free + int(r.purchased or 0)
        return (int(r.spent or 0) > limit) and (int(r.is_trusted or 0) == 0)

    rows = []
    for r in rows_raw:
        sus = suspicious_of(r)
        if view == 'sus' and not sus:
            continue
        if view == 'banned' and not int(r.is_banned or 0):
            continue
        rows.append({
            'id': r.id,
            'email': r.email,
            'tokens': int(r.tokens or 0),
            'spent': int(r.spent or 0),
            'purchased': int(r.purchased or 0),
            'claims': int(r.claims or 0),
            'reward': int(r.reward or 0),
            'is_banned': int(r.is_banned or 0),
            'is_trusted': int(r.is_trusted or 0),
            'suspicious': sus,
            'created': r.created,
        })

    return render_template('admin_users.html', rows=rows, q=q, sort=sort, view=view)


# ---------------------------------------------------------------------------
# KULLANICI DETAYI (sipariş + işlem geçmişi)
@admin_bp.get('/user/<int:user_id>')
@login_required
def user_detail(user_id: int):
    u = User.query.get_or_404(user_id)

    # özet rakamlar
    spent = db.session.execute(
        text("""SELECT COALESCE(SUM(CAST(json_extract(meta,'$.tokens') AS INTEGER)),0)
                FROM audit_event WHERE user_id=:uid AND event='token_spent'"""),
        {'uid': user_id}
    ).scalar() or 0

    purchased = db.session.execute(
        text("""SELECT COALESCE(SUM(CAST(json_extract(meta,'$.tokens') AS INTEGER)),0)
                FROM audit_event WHERE user_id=:uid AND event='token_purchase'"""),
        {'uid': user_id}
    ).scalar() or 0

    claim_count = db.session.execute(
        text("""SELECT COUNT(*) FROM audit_event
                WHERE user_id=:uid AND event='daily_claim'"""),
        {'uid': user_id}
    ).scalar() or 0

    reward_sum = db.session.execute(
        text("""SELECT COALESCE(SUM(CAST(json_extract(meta,'$.tokens') AS INTEGER)),0)
                FROM audit_event WHERE user_id=:uid AND event='reward_claim'"""),
        {'uid': user_id}
    ).scalar() or 0

    # ŞÜPHELİ?
    free = 3 + int(claim_count) + int(reward_sum)
    limit = free + int(purchased)
    suspicious = (int(spent) > limit) and (int(u.is_trusted or 0) == 0)

    # Sipariş geçmişi
    pur_q = (AuditEvent.query
             .filter(AuditEvent.user_id == user_id, AuditEvent.event == 'token_purchase')
             .order_by(AuditEvent.created_at.desc())
             .limit(50))

    orders = []
    for ev in pur_q.all():
        m = {}
        try:
            m = json.loads(ev.meta or '{}')
        except Exception:
            pass
        orders.append({
            'created': ev.created_at,
            'qty':     m.get('tokens') or m.get('qty') or 0,
            'amount':  m.get('amount'),
            'currency': m.get('currency'),
            'provider': m.get('provider') or m.get('gateway') or '-',
            'order_no': m.get('order_id') or m.get('order') or m.get('payment_id') or '-',
            'txn_id':   m.get('txn_id') or m.get('transaction_id') or '-',
        })

    # İşlem geçmişi
    events_wanted = ('register', 'login', 'upload', 'daily_claim',
                     'token_spent', 'token_purchase', 'verify_email', 'reward_claim')
    ev_q = (AuditEvent.query
            .filter(AuditEvent.user_id == user_id, AuditEvent.event.in_(events_wanted))
            .order_by(AuditEvent.created_at.desc())
            .limit(50))

    activities = []
    for ev in ev_q.all():
        try:
            m = json.loads(ev.meta or '{}')
        except Exception:
            m = {}

        detail = '—'
        if ev.event == 'upload' and m.get('files') is not None:
            detail = f"{m.get('files')} dosya"
        elif ev.event == 'token_spent' and m.get('tokens') is not None:
            detail = f"-{m.get('tokens')} token"
        elif ev.event == 'token_purchase' and m.get('tokens') is not None:
            cur = m.get('currency') or ''
            detail = f"+{m.get('tokens')} token {cur}".strip()
        elif ev.event == 'daily_claim':
            detail = f"Günlük ödül +{m.get('tokens', 1)}"
        elif ev.event == 'reward_claim':
            detail = f"Ödül +{m.get('tokens', 0)}"

        activities.append({
            'created': ev.created_at,
            'event': ev.event,
            'detail': detail
        })

    return render_template('admin_user_detail.html',
                           user=u,
                           tokens_current=u.tokens or 0,
                           tokens_spent=int(spent),
                           tokens_purchased=int(purchased),
                           daily_claims=int(claim_count),
                           reward_sum=int(reward_sum),
                           suspicious=suspicious,
                           orders=orders,
                           activities=activities)


# ---------------------------------------------------------------------------
# ANALYTICS (mevcut grafikleri koruduk)
@admin_bp.get('/analytics')
@login_required
def analytics_page():
    return render_template('admin_analytics.html')


@admin_bp.get('/api/metrics')
@login_required
def api_metrics():
    rng = (request.args.get('range') or '30d').lower().strip()

    if rng == '5y':
        now_local = datetime.now()
        start_year = now_local.year - 4
        years = [str(y) for y in range(start_year, now_local.year + 1)]
        start_utc = datetime(year=start_year, month=1, day=1).strftime('%Y-%m-%d %H:%M:%S')

        q = db.session.execute(text("""
            SELECT strftime('%Y', datetime(created_at, 'localtime')) AS yyyy, event, COUNT(*) AS cnt
            FROM audit_event
            WHERE datetime(created_at) >= datetime(:start)
            GROUP BY yyyy, event
            ORDER BY yyyy
        """), {'start': start_utc}).fetchall()

        series = {'register': {y:0 for y in years},
                  'login':    {y:0 for y in years},
                  'upload':   {y:0 for y in years}}
        for yyyy, ev, cnt in q:
            if ev in series and yyyy in series[ev]:
                series[ev][yyyy] = int(cnt or 0)

        return jsonify({
            'mode': 'years',
            'years': years,
            'yearly': {k:[series[k][y] for y in years] for k in series},
        })

    # days mode
    try:
        days = int(rng[:-1]) if rng.endswith('d') else 30
    except Exception:
        days = 30
    days = max(1, min(1825, days))

    start_utc = (datetime.utcnow() - timedelta(days=days)).strftime('%Y-%m-%d %H:%M:%S')

    q1 = db.session.execute(text("""
        SELECT strftime('%Y-%m-%d', datetime(created_at, 'localtime')) AS day,
               event, COUNT(*) AS cnt
        FROM audit_event
        WHERE datetime(created_at) >= datetime(:start)
        GROUP BY day, event
        ORDER BY day
    """), {'start': start_utc}).fetchall()

    q2 = db.session.execute(text("""
        SELECT CAST(strftime('%H', datetime(created_at, 'localtime')) AS INTEGER) AS hh,
               event, COUNT(*) AS cnt
        FROM audit_event
        WHERE datetime(created_at) >= datetime(:start)
        GROUP BY hh, event
        ORDER BY hh
    """), {'start': start_utc}).fetchall()

    q_upload_meta = db.session.execute(text("""
        SELECT strftime('%Y-%m-%d', datetime(created_at, 'localtime')) AS day, meta
        FROM audit_event
        WHERE event='upload' AND datetime(created_at) >= datetime(:start)
    """), {'start': start_utc}).fetchall()

    q_purchase = db.session.execute(text("""
        SELECT strftime('%Y-%m-%d', datetime(created_at, 'localtime')) AS day,
               user_id, meta
        FROM audit_event
        WHERE event='token_purchase' AND datetime(created_at) >= datetime(:start)
    """), {'start': start_utc}).fetchall()

    now_local = datetime.now()
    start_local = now_local - timedelta(days=days)
    days_list = [(start_local + timedelta(days=i)).strftime('%Y-%m-%d') for i in range(days+1)]

    series = {'register': {d:0 for d in days_list},
              'login':    {d:0 for d in days_list},
              'upload':   {d:0 for d in days_list}}
    for day, ev, cnt in q1:
        if ev in series and day in series[ev]:
            series[ev][day] = int(cnt or 0)

    files_total = {d:0 for d in days_list}
    for day, meta_txt in q_upload_meta:
        try:
            m = json.loads(meta_txt or '{}')
            files_total[day] = files_total.get(day, 0) + int(m.get('files', 0))
        except Exception:
            pass

    hours = list(range(24))
    hourly = {'register':[0]*24, 'login':[0]*24, 'upload':[0]*24}
    for hh, ev, cnt in q2:
        if ev in hourly and 0 <= hh < 24:
            hourly[ev][hh] = int(cnt or 0)

    buyers_sets = {d:set() for d in days_list}
    tokens_sold = {d:0 for d in days_list}
    for day, user_id, meta_txt in q_purchase:
        if day not in tokens_sold:
            continue
        try:
            m = json.loads(meta_txt or '{}')
            tokens = int(m.get('tokens', 0))
        except Exception:
            tokens = 0
        tokens_sold[day] += max(0, tokens)
        if user_id is not None:
            buyers_sets[day].add(int(user_id))
    token_buyers = {d: len(buyers_sets[d]) for d in days_list}

    return jsonify({
        'mode': 'days',
        'days': days_list,
        'daily': {k:[series[k][d] for d in days_list] for k in series},
        'daily_files': [files_total[d] for d in days_list],
        'hours': hours,
        'hourly': hourly,
        'range_days': days,
        'tokens_sold': [tokens_sold[d] for d in days_list],
        'token_buyers': [token_buyers[d] for d in days_list],
    })


# ---------------------------------------------------------------------------
# Yönetim aksiyonları: ban / unban / trust / untrust
@admin_bp.post('/user/<int:user_id>/ban')
@login_required
def user_ban(user_id):
    u = User.query.get_or_404(user_id)
    u.is_banned = 1
    try:
        db.session.commit()
        flash('Kullanıcı banlandı.', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'Ban hatası: {e}', 'error')
    return redirect(request.referrer or url_for('admin.users_page'))

@admin_bp.post('/user/<int:user_id>/unban')
@login_required
def user_unban(user_id):
    u = User.query.get_or_404(user_id)
    u.is_banned = 0
    try:
        db.session.commit()
        flash('Ban kaldırıldı.', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'Hata: {e}', 'error')
    return redirect(request.referrer or url_for('admin.users_page'))

@admin_bp.post('/user/<int:user_id>/trust')
@login_required
def user_trust(user_id):
    u = User.query.get_or_404(user_id)
    u.is_trusted = 1
    try:
        db.session.commit()
        flash('Kullanıcı şüpheliden çıkarıldı (güvenilir).', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'Hata: {e}', 'error')
    return redirect(request.referrer or url_for('admin.users_page'))

@admin_bp.post('/user/<int:user_id>/untrust')
@login_required
def user_untrust(user_id):
    u = User.query.get_or_404(user_id)
    u.is_trusted = 0
    try:
        db.session.commit()
        flash('Kullanıcı yeniden şüpheli kurallarına tabi.', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'Hata: {e}', 'error')
    return redirect(request.referrer or url_for('admin.users_page'))


# ---------------------------------------------------------------------------
# (İsteğe bağlı) test seed uçları
@admin_bp.post('/api/seed')
@login_required
def api_seed():
    now = datetime.utcnow()
    items = []
    for d in range(7, -1, -1):
        base = now - timedelta(days=d)
        r = random.randint(1, 4)
        l = r + random.randint(0, 3)
        u = random.randint(0, 5)
        for _ in range(r):
            items.append(AuditEvent(event='register', created_at=base - timedelta(hours=random.randint(0,23))))
        for _ in range(l):
            items.append(AuditEvent(event='login', created_at=base - timedelta(hours=random.randint(0,23))))
        for _ in range(u):
            items.append(AuditEvent(event='upload', created_at=base - timedelta(hours=random.randint(0,23)),
                                    meta=json.dumps({'files': random.randint(1, 8)})))
    try:
        db.session.bulk_save_objects(items)
        db.session.commit()
        return jsonify(ok=True, inserted=len(items))
    except Exception as e:
        db.session.rollback()
        return jsonify(ok=False, error=str(e)), 500

@admin_bp.post('/api/seed-years')
@login_required
def api_seed_years():
    now_local = datetime.now()
    start_year = now_local.year - 4
    items = []
    for y in range(start_year, now_local.year + 1):
        r = random.randint(5, 20)
        l = r + random.randint(5, 30)
        u = random.randint(10, 50)
        total = r + l + u
        for i in range(total):
            month = random.randint(1, 12)
            day = random.randint(1, 28)
            hour = random.randint(0, 23)
            ev = 'register' if i < r else ('login' if i < r + l else 'upload')
            items.append(AuditEvent(event=ev, created_at=datetime(y, month, day, hour, 0, 0),
                                    meta=json.dumps({'files': random.randint(1, 6)}) if ev=='upload' else None))
    try:
        db.session.bulk_save_objects(items)
        db.session.commit()
        return jsonify(ok=True, inserted=len(items))
    except Exception as e:
        db.session.rollback()
        return jsonify(ok=False, error=str(e)), 500

@admin_bp.post('/api/seed-purchases')
@login_required
def api_seed_purchases():
    now = datetime.utcnow()
    items = []
    for d in range(30, -1, -1):
        base = now - timedelta(days=d)
        k = random.randint(0, 5)
        for _ in range(k):
            uid = random.randint(1, 50)
            tokens = random.choice([10, 20, 50, 100, 250])
            hour = random.randint(0, 23)
            items.append(
                AuditEvent(
                    user_id=uid,
                    event='token_purchase',
                    created_at=base - timedelta(hours=random.randint(0, hour)),
                    meta=json.dumps({'tokens': tokens, 'currency': 'TRY', 'amount': tokens * 1.0})
                )
            )
    try:
        db.session.bulk_save_objects(items)
        db.session.commit()
        return jsonify(ok=True, inserted=len(items))
    except Exception as e:
        db.session.rollback()
        return jsonify(ok=False, error=str(e)), 500
