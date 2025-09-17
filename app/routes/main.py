# app/routes/main.py
from flask import Blueprint, render_template
from flask_login import current_user

main_bp = Blueprint('main', __name__)

@main_bp.get('/')
def index():
    daily_remaining_seconds = 0
    if current_user.is_authenticated:
        try:
            daily_remaining_seconds = current_user.seconds_until_daily()
        except Exception:
            daily_remaining_seconds = 0
    return render_template('index.html', daily_remaining_seconds=daily_remaining_seconds)
