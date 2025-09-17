@echo off
:: ===== PictureScaler launcher =====

:: Konsolu UTF-8 yap (Türkçe karakterler için)
chcp 65001 >nul
setlocal

:: Proje klasörüne geç
cd /d "C:\Users\Ömer\Desktop\printify"

:: (İsteğe bağlı) Sanal ortam varsa etkinleştir
if exist ".venv\Scripts\activate.bat" call ".venv\Scripts\activate.bat"

:: ---------- Uygulama ayarları ----------
:: Admin paneli için yetkili e-postalar (virgülle çoğaltılabilir)
set "ADMIN_EMAILS=picturescalerofficial@gmail.com"

:: Yerelde test: e-posta doğrulamasını kapat (1 yaparsan zorunlu olur)
set "REQUIRE_EMAIL_VERIFICATION=0"

:: Python çıktısını UTF-8 zorla (bazı Windows kurulumlarında faydalı)
set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"

:: SMTP / Gmail (Uygulama Şifresi kullan)
set "MAIL_ENABLED=1"
set "SMTP_HOST=smtp.gmail.com"
set "SMTP_PORT=587"
set "SMTP_TLS=1"
set "SMTP_SSL=0"
set "SMTP_USER=picturescalerofficial@gmail.com"
set "SMTP_FROM=picturescalerofficial@gmail.com"
set "SMTP_PASS=xsdvvikmbrlszuxe"

:: ---------- Sunucuyu çalıştır ----------
python run.py

echo.
echo Sunucu kapandi. Pencereyi kapatmak icin bir tusa basin...
pause >nul
endlocal
