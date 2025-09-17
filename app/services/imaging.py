# app/services/imaging.py
from PIL import Image
from pathlib import Path
import os

# 8 temel ölçü (px) — dikey (portre)
BOYUTLAR_8LI_PORTRAIT = [
    (360, 504),   # 5x7"
    (576, 720),   # 8x10"
    (648, 864),   # 9x12"
    (792, 1008),  # 11x14"
    (1152, 1440), # 16x20"
    (1296, 1728), # 18x24"
    (1728, 2592), # 24x36"
    (1188, 1685)  # ISO A2
]

# YATAY: (w,h) -> (h,w) çevir
BOYUTLAR_8LI_LANDSCAPE = [(h, w) for (w, h) in BOYUTLAR_8LI_PORTRAIT]

LABELS_8LI = ["5x7", "8x10", "9x12", "11x14", "16x20", "18x24", "24x36", "ISO A2"]

try:
    RESAMPLE = Image.Resampling.LANCZOS
except Exception:
    RESAMPLE = Image.LANCZOS

def get_sizes(orientation: str):
    """'portrait' ya da 'landscape' gelir; uygun boyut listesi döner."""
    if str(orientation).lower() == 'landscape':
        return BOYUTLAR_8LI_LANDSCAPE
    return BOYUTLAR_8LI_PORTRAIT

def resimleri_numaralandirarak_kaydet(
    klasor_yolu: str,
    boyutlar: list[tuple[int, int]],
    hedef_klasor: str,
    scale: int = 5
):
    scale = max(1, min(int(scale), 5))
    os.makedirs(hedef_klasor, exist_ok=True)

    for dosya_adi in os.listdir(klasor_yolu):
        if not dosya_adi.lower().endswith((".png", ".jpg", ".jpeg")):
            continue
        p = os.path.join(klasor_yolu, dosya_adi)
        try:
            with Image.open(p) as im:
                if im.mode not in ("RGB", "L"):
                    im = im.convert("RGB")
                base = Path(dosya_adi).stem
                alt_klasor = os.path.join(hedef_klasor, base)
                os.makedirs(alt_klasor, exist_ok=True)
                for index, (w, h) in enumerate(boyutlar):
                    out_w, out_h = w * scale, h * scale
                    out = im.resize((out_w, out_h), RESAMPLE)
                    label = LABELS_8LI[index] if index < len(LABELS_8LI) else f"size{index+1}"
                    dst = os.path.join(alt_klasor, f"{label} {base}.jpg")
                    out.save(dst, "JPEG", quality=100, dpi=(300, 300))
        except Exception as e:
            print(f"Hata: {dosya_adi} → {e}")
