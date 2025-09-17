# run.py
from app import create_app

app = create_app()

if __name__ == '__main__':
    # Debug açıldı. Hata olursa tarayıcıda ayrıntılı stack trace göreceksin.
    app.run(host='127.0.0.1', port=5000, debug=True, use_reloader=False)
