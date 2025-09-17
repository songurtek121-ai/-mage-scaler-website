# app/services/packing.py
import io, zipfile
from pathlib import Path

def build_zip_from_folder(folder: str) -> io.BytesIO:
    zip_bytes = io.BytesIO()
    with zipfile.ZipFile(zip_bytes, 'w', zipfile.ZIP_DEFLATED) as zf:
        for p in Path(folder).rglob('*'):
            if p.is_file():
                zf.write(p, arcname=str(p.relative_to(folder)))
    zip_bytes.seek(0)
    return zip_bytes
