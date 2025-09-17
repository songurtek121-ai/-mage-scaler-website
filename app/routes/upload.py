# app/routes/upload.py
from datetime import datetime
from pathlib import Path
import os, io, zipfile, shutil, json

from flask import Blueprint, current_app, request, send_file, Response
from flask_login import login_required, current_user
from werkzeug.utils import secure_filename

from PIL import Image

from .. import db
from ..models import AuditEvent

upload_bp = Blueprint("upload", __name__)

# 8 temel ölçü (px) — portre (dikey)
PORTRAIT_SIZES = [
    (360, 504),    # 5x7"
    (576, 720),    # 8x10"
    (648, 864),    # 9x12"
    (792, 1008),   # 11x14"
    (1152, 1440),  # 16x20"
    (1296, 1728),  # 18x24"
    (1728, 2592),  # 24x36"
    (1188, 1685),  # ISO A2
]
LABELS_8 = ["5x7", "8x10", "9x12", "11x14", "16x20", "18x24", "24x36", "ISO A2"]

try:
    RESAMPLE = Image.Resampling.LANCZOS
except Exception:
    RESAMPLE = Image.LANCZOS


def _allowed(filename: str) -> bool:
    return filename.lower().endswith((".png", ".jpg", ".jpeg"))


def _sizes_for_orientation(orientation: str):
    if (orientation or "").lower() == "landscape":
        return [(h, w) for (w, h) in PORTRAIT_SIZES]
    return PORTRAIT_SIZES


def _process_folder(src_dir: Path, out_dir: Path, sizes, scale: int):
    """
    src_dir içindeki her görsel için out_dir/<basename>/ altında 8'li çıktı üretir.
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    produced_files = 0

    for name in os.listdir(src_dir):
        if not _allowed(name):
            continue
        p = src_dir / name
        try:
            with Image.open(p) as im:
                if im.mode not in ("RGB", "L"):
                    im = im.convert("RGB")

                base = Path(name).stem
                sub = out_dir / base
                sub.mkdir(exist_ok=True)

                for idx, (w, h) in enumerate(sizes):
                    out_w, out_h = int(w * scale), int(h * scale)
                    out_im = im.resize((out_w, out_h), RESAMPLE)
                    label = LABELS_8[idx] if idx < len(LABELS_8) else f"size{idx+1}"
                    dst = sub / f"{label} {base}.jpg"
                    out_im.save(dst, "JPEG", quality=100, dpi=(300, 300))
                    produced_files += 1
        except Exception as e:
            current_app.logger.error(f"[UPLOAD] {name} işlenemedi: {e}")

    return produced_files


@upload_bp.post("/upload")
@login_required
def upload():
    """
    - Seçilen dosya sayısı kadar token gerekir (1 dosya = 1 token).
    - Yetersiz token -> 402 ve X-Required-Tokens / X-Tokens-Remaining header’ları.
    - Başarılı işlem:
        * user.tokens -= file_count
        * audit_event: upload (meta.files = file_count)
        * audit_event: token_spent (meta.tokens = file_count, reason='upload')
        * ZIP döner, X-Tokens-Remaining header’ı set edilir.
    """
    files = request.files.getlist("files")
    if not files:
        return Response("Dosya bulunamadı", status=400)

    # Form parametreleri
    orientation = (request.form.get("orientation") or "portrait").lower().strip()
    scale = request.form.get("scale", "5")
    try:
        scale = max(1, min(int(scale), 5))
    except Exception:
        scale = 5

    # Yüklenebilir dosyaları süz
    accepted = []
    original_names = []
    for f in files:
        if not f:
            continue
        name = secure_filename(f.filename or "")
        if not name or not _allowed(name):
            continue
        accepted.append((f, name))
        original_names.append(name)

    file_count = len(accepted)
    if file_count == 0:
        return Response("Yalnızca PNG/JPG kabul edilir", status=400)

    # Gerekli token kontrolü
    need = file_count  # 1 dosya = 1 token
    have = int(current_user.tokens or 0)
    if have < need:
        resp = Response("Yetersiz token", status=402)
        resp.headers["X-Required-Tokens"] = str(need)
        resp.headers["X-Tokens-Remaining"] = str(have)
        return resp

    # Çalışma klasörleri (instance/uploads & instance/outputs)
    inst = Path(current_app.instance_path)
    uploads_dir = inst / current_app.config.get("UPLOADS_DIRNAME", "uploads")
    outputs_dir = inst / current_app.config.get("OUTPUTS_DIRNAME", "outputs")
    uploads_dir.mkdir(parents=True, exist_ok=True)
    outputs_dir.mkdir(parents=True, exist_ok=True)

    job_id = datetime.utcnow().strftime("%Y%m%d-%H%M%S-%f")
    job_in = uploads_dir / job_id
    job_out = outputs_dir / job_id
    job_in.mkdir(parents=True, exist_ok=True)
    job_out.mkdir(parents=True, exist_ok=True)

    # Orijinalleri kaydet
    for f, name in accepted:
        (job_in / name).write_bytes(f.read())

    # İşle
    try:
        sizes = _sizes_for_orientation(orientation)
        _ = _process_folder(job_in, job_out, sizes, scale=scale)
    except Exception as e:
        shutil.rmtree(job_in, ignore_errors=True)
        shutil.rmtree(job_out, ignore_errors=True)
        current_app.logger.exception("[UPLOAD] İşleme hatası")
        return Response("İşleme hatası", status=500)

    # ZIP’e paketle
    zip_bytes = io.BytesIO()
    with zipfile.ZipFile(zip_bytes, "w", zipfile.ZIP_DEFLATED) as zf:
        for p in job_out.rglob("*"):
            if p.is_file():
                zf.write(p, arcname=str(p.relative_to(job_out)))
    zip_bytes.seek(0)

    # Token düş + audit log
    now = datetime.utcnow()
    try:
        # Kullanıcı tokenlarını düş
        current_user.tokens = have - need

        # upload eventi (grafikler için dosya sayısı önemli)
        db.session.add(
            AuditEvent(
                user_id=current_user.id,
                event="upload",
                created_at=now,
                meta=json.dumps({"files": file_count, "orientation": orientation, "scale": scale}),
            )
        )

        # token_spent eventi (admin “Harcanan” sütunu için)
        db.session.add(
            AuditEvent(
                user_id=current_user.id,
                event="token_spent",
                created_at=now,
                meta=json.dumps({"tokens": need, "reason": "upload", "files": file_count}),
            )
        )

        db.session.commit()
    except Exception as e:
        db.session.rollback()
        current_app.logger.exception("[UPLOAD] Token düşme/log yazma hatası")
        return Response("Kayıt hatası", status=500)
    finally:
        # Geçici klasörleri sil (istersen saklayabilirsin)
        shutil.rmtree(job_in, ignore_errors=True)
        shutil.rmtree(job_out, ignore_errors=True)

    # Dosya adı
    if file_count == 1 and original_names:
        base = Path(original_names[0]).stem
        filename = f"{base}.zip"
    else:
        filename = "pack.zip"

    # Yanıt
    resp = send_file(
        zip_bytes,
        as_attachment=True,
        download_name=filename,
        mimetype="application/zip",
    )
    resp.headers["X-Tokens-Remaining"] = str(int(current_user.tokens or 0))
    return resp
