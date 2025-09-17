# app/__init__.py
from pathlib import Path
from flask import Flask, redirect, url_for, request, abort
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, current_user
from sqlalchemy import text

db = SQLAlchemy()
login_manager = LoginManager()


def create_app():
    app = Flask(__name__, instance_relative_config=True)
    app.config.from_object('config')

    # --- instance klasörleri ---
    inst = Path(app.instance_path)
    inst.mkdir(parents=True, exist_ok=True)
    (inst / app.config.get('UPLOADS_DIRNAME', 'uploads')).mkdir(parents=True, exist_ok=True)
    (inst / app.config.get('OUTPUTS_DIRNAME', 'outputs')).mkdir(parents=True, exist_ok=True)

    # --- eklentiler ---
    db.init_app(app)
    login_manager.init_app(app)
    login_manager.login_view = 'auth.login_page'

    # --- modelleri yükle & DB oluştur/patch ---
    with app.app_context():
        # MODELLER: (User, AuditEvent, Coupon, CouponRedemption)
        from .models import User, AuditEvent, Coupon, CouponRedemption  # noqa
        db.create_all()

        # ---- SQLite kolon yamaları (varsa eksikleri ekle) ----
        try:
            # USER tablosu
            rows_user = db.session.execute(text("PRAGMA table_info(user)")).fetchall()
            existing_user_cols = {row[1] for row in rows_user}
            add_user_cols = {
                'tokens':           "INTEGER NOT NULL DEFAULT 0",
                'is_verified':      "INTEGER NOT NULL DEFAULT 0",
                'verify_token':     "VARCHAR(128)",
                'verify_sent_at':   "DATETIME",
                'last_daily_claim': "DATETIME",
                'is_admin':         "INTEGER NOT NULL DEFAULT 0",
                'is_banned':        "INTEGER NOT NULL DEFAULT 0",
                'is_trusted':       "INTEGER NOT NULL DEFAULT 0",
                'last_login_at':    "DATETIME",
            }
            for col, ddl in add_user_cols.items():
                if col not in existing_user_cols:
                    db.session.execute(text(f"ALTER TABLE user ADD COLUMN {col} {ddl}"))

            # AUDIT_EVENT tablosu
            rows_audit = db.session.execute(text("PRAGMA table_info(audit_event)")).fetchall()
            existing_audit_cols = {row[1] for row in rows_audit}
            add_audit_cols = {
                'meta': "TEXT",
            }
            for col, ddl in add_audit_cols.items():
                if col not in existing_audit_cols:
                    db.session.execute(text(f"ALTER TABLE audit_event ADD COLUMN {col} {ddl}"))

            db.session.commit()
        except Exception as e:
            db.session.rollback()
            app.logger.error(f"[DB PATCH] Hata: {e}")

    # --- yetkisiz -> login / XHR:401 ---
    @login_manager.unauthorized_handler
    def _unauthorized():
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return ('Unauthorized', 401)
        return redirect(url_for('auth.login_page', next=request.url))

    # --- Ban Kapısı: banlılar yazma işlemi yapamaz ---
    @app.before_request
    def _ban_gate():
        # GET istekleri serbest, yazma isteklerini engelle
        if request.method in ('POST', 'PUT', 'PATCH', 'DELETE'):
            if getattr(current_user, 'is_authenticated', False):
                # admin blueprint'i kendi içinde çalışsın
                if request.blueprint == 'admin':
                    return
                if getattr(current_user, 'is_banned', 0):
                    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                        return ('Forbidden', 403)
                    abort(403)

    # --- blueprint'ler ---
    from .routes.main import main_bp
    from .routes.upload import upload_bp
    from .routes.auth import auth_bp
    from .routes.rewards import rewards_bp
    from .routes.admin import admin_bp
    from .routes.payments import payments_bp
    from .routes.profile import profile_bp
    # Kuponlar (eklediysen):
    try:
        from .routes.coupons import coupons_bp
        app.register_blueprint(coupons_bp)
    except Exception:
        # coupons_bp yoksa sessiz geç
        pass

    app.register_blueprint(main_bp)
    app.register_blueprint(upload_bp)
    app.register_blueprint(auth_bp)
    app.register_blueprint(rewards_bp)
    app.register_blueprint(admin_bp)
    app.register_blueprint(payments_bp)
    app.register_blueprint(profile_bp)

    return app


@login_manager.user_loader
def load_user(user_id: str):
    from .models import User
    try:
        return User.query.get(int(user_id))
    except Exception:
        return None
