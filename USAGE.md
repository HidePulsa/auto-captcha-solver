# Auto-Captcha-Solver — Dokumentasi Lengkap

Self-hosted AI captcha solver. Menggabungkan **offline ML classifier** (untuk reCAPTCHA v2) dan **vision LLM** (untuk hCaptcha). Tidak perlu bayar 2captcha.

---

## Daftar Isi
1. [Requirements](#requirements)
2. [Instalasi](#instalasi)
3. [Konfigurasi](#konfigurasi)
4. [reCAPTCHA v2 — Offline Classifier](#recaptcha-v2--offline-classifier)
5. [hCaptcha — Vision LLM Solver](#hcaptcha--vision-llm-solver)
6. [HTTP API Server (2captcha-compatible)](#http-api-server-2captcha-compatible)
7. [Pakai sebagai Python Library](#pakai-sebagai-python-library)
8. [Training Model Sendiri](#training-model-sendiri)
9. [Arsitektur](#arsitektur)
10. [Known Limitations](#known-limitations)
11. [Referensi Dataset](#referensi-dataset)

---

## Requirements

```
Python 3.10+
Camoufox (browser automation)
PyTorch (untuk reCAPTCHA classifier)
httpx
Pillow
```

VPS/server requirements:
- RAM minimal **2GB** (4GB recommended untuk training)
- CPU: 2+ core
- Tidak butuh GPU

---

## Instalasi

### 1. Clone repo

```bash
git clone https://github.com/HidePulsa/auto-captcha-solver.git
cd auto-captcha-solver
```

### 2. Install dependencies

```bash
pip install -r requirements.txt
```

### 3. Install Camoufox browser

```bash
python -m camoufox fetch
```

> ⚠️ Kalau di headless server (VPS), butuh `xvfb-run`:
> ```bash
> apt install -y xvfb
> ```

### 4. Download model reCAPTCHA (sudah ada di repo)

```bash
ls models/recaptcha_classifier.pt  # 6MB, F1=91.4%
```

Model sudah include di repo — tidak perlu download terpisah.

---

## Konfigurasi

Set environment variables sebelum run:

```bash
# Vision LLM backend (OpenAI-compatible)
export VISION_BASE_URL="http://YOUR_SERVER:20128/v1"
export VISION_MODEL="ag/gemini-3.8-flash-high"   # WAJIB support vision/image
export VISION_API_KEY="sk-..."

# Proxy residential (wajib untuk hCaptcha, agar tidak di-block)
export PROXY_SERVER="http://gw.dataimpulse.com:823"
export PROXY_USER="your_user__cr.id"
export PROXY_PASS="your_password"
```

> ⚠️ **Penting untuk 9router/custom backend**: 9router return SSE by default.
> Solver sudah otomatis tambah `"stream": False` di setiap request — tidak perlu config tambahan.

> ⚠️ **Claude via 9router tidak support image base64**. Gunakan Gemini:
> - ✅ `ag/gemini-3.8-flash-high` — terbaik, support vision
> - ✅ `ag/gemini-3.8-flash-medium` — balance speed/quality
> - ❌ `ag/claude-sonnet-4-6` — tidak support base64 image via 9router

---

## reCAPTCHA v2 — Offline Classifier

**Tidak butuh AI vision / API call** — inference lokal, ~5ms per tile.

### Cara pakai langsung

```python
from solver.recaptcha_classifier import ReCaptchaClassifier
from PIL import Image

# Load model (otomatis dari models/recaptcha_classifier.pt)
clf = ReCaptchaClassifier()

# Predict 1 tile
result = clf.predict_tile("path/to/tile.png")
# Output: {"bicycle": 0.02, "bus": 0.01, "car": 0.97, "crosswalk": 0.03, "hydrant": 0.01}

# Predict batch tiles
tiles = ["tile0.png", "tile1.png", "tile2.png"]
results = clf.predict_batch(tiles)

# Solve: task text + tile images → return index tile yang harus diklik
cells = clf.solve("Select all images with a fire hydrant", tiles)
# Output: [2, 5, 7]  ← index tile yang mengandung hydrant
```

### Task text yang di-support

| Task Text | Label yang dideteksi |
|---|---|
| "bicycle", "bike" | bicycle |
| "bus" | bus |
| "car", "vehicle", "automobile" | car |
| "crosswalk", "pedestrian crossing", "zebra crossing" | crosswalk |
| "fire hydrant", "hydrant" | hydrant |

### Integrasi dengan Camoufox

```python
from camoufox.sync_api import Camoufox
from solver.recaptcha_classifier import ReCaptchaClassifier
import tempfile, os

clf = ReCaptchaClassifier()

with Camoufox(headless=True) as browser:
    page = browser.new_page()
    page.goto("https://example.com/with-recaptcha")
    page.wait_for_timeout(3000)

    # Screenshot grid tiles (contoh: crop 9 tiles dari screenshot)
    page.screenshot(path="/tmp/recaptcha_full.png")
    
    # Detect task text dari page
    task_text = page.evaluate("""() => {
        const el = document.querySelector('.rc-imageselect-desc-no-canonical');
        return el ? el.innerText : '';
    }""")
    
    # Crop dan classify tiles
    # (implementasi crop tergantung layout reCAPTCHA)
    tile_paths = crop_recaptcha_tiles("/tmp/recaptcha_full.png")
    cells = clf.solve(task_text, tile_paths)
    
    # Klik tiles
    for cell in cells:
        row, col = divmod(cell, 3)
        # klik koordinat
        page.mouse.click(x_start + col * tile_w, y_start + row * tile_h)
```

---

## hCaptcha — Vision LLM Solver

Butuh **proxy residential** + **vision LLM** (Gemini recommended).

### Basic usage

```python
from camoufox.sync_api import Camoufox
from solver.vision import VisionClient
from solver.hcaptcha import HcaptchaSolver

PROXY = {
    "server": "http://gw.dataimpulse.com:823",
    "username": "user__cr.id",    # DataImpulse residential
    "password": "password"
}

vision = VisionClient(
    base_url="http://YOUR_SERVER:20128/v1",
    model="ag/gemini-3.8-flash-high",
    api_key="sk-..."
)
solver = HcaptchaSolver(vision)

with Camoufox(headless=False, proxy=PROXY, humanize=False, geoip=True) as browser:
    page = browser.new_page()
    page.set_viewport_size({"width": 1280, "height": 900})
    page.goto("https://example.com/with-hcaptcha")
    page.wait_for_timeout(5000)
    
    ok = solver.solve(page, timeout_s=120)
    print("Solved:", ok)
```

### hCaptcha flow (internal)

```
1. Detect iframe hCaptcha
2. Click checkbox iframe → trigger challenge popup
3. Scroll challenge into viewport
4. Screenshot viewport (bukan full_page!)
5. Kirim ke vision LLM + prompt → return JSON {"task":"...", "cells":[0,4]}
6. Klik canvas di koordinat yang dihitung (grid 3x3)
7. Click verify button (.button-submit dalam challenge frame)
8. Poll token: textarea[name="h-captcha-response"] atau hcaptcha.getResponse()
```

### Important: headless vs headful

```bash
# VPS tanpa display → wajib xvfb-run
xvfb-run -a python3 your_script.py

# Atau set headless=True (tapi LEBIH MUDAH DIDETEKSI oleh hCaptcha)
Camoufox(headless=True, ...)
```

### Proxy — wajib untuk hCaptcha

hCaptcha block IP datacenter. Wajib pakai residential proxy:

```python
PROXY = {
    "server": "http://gw.dataimpulse.com:823",  # :823 = rotating per request
    "username": "user__cr.id",                   # cr.id = exit node Indonesia
    "password": "pass"
}
# WAJIB tambah geoip=True ke Camoufox
Camoufox(..., proxy=PROXY, geoip=True)
```

---

## HTTP API Server (2captcha-compatible)

Biar bisa dipakai oleh script yang sudah pakai 2captcha API.

### Start server

```bash
python -m server.api --port 8080 --host 0.0.0.0
```

### Submit job

```bash
curl -X POST http://localhost:8080/in.php \
  -H "Content-Type: application/json" \
  -d '{
    "method": "hcaptcha",
    "sitekey": "your-sitekey",
    "pageurl": "https://example.com",
    "key": "demo"
  }'
# Response: {"status":1,"request":"abc123def456"}
```

### Poll result

```bash
# Poll setiap 5 detik sampai ready
curl "http://localhost:8080/res.php?action=get&id=abc123def456"

# Masih proses:  {"status":0,"request":"CAPCHA_NOT_READY"}
# Selesai:       {"status":1,"request":"P1_token_here..."}
# Error:         {"status":0,"request":"ERROR_CAPTCHA_UNSOLVABLE"}
```

### Environment untuk server

```bash
# Opsional: set proxy untuk semua solve job
export PROXY="http://user:pass@gw.dataimpulse.com:823"

python -m server.api --port 8080
```

---

## Pakai sebagai Python Library

### Auto-detect captcha type

```python
from camoufox.sync_api import Camoufox
from solver.vision import VisionClient
from solver.core import Solver

vision = VisionClient(
    base_url="http://YOUR_SERVER:20128/v1",
    model="ag/gemini-3.8-flash-high",
    api_key="sk-..."
)
solver = Solver(vision)

with Camoufox(headless=False, proxy=PROXY, geoip=True) as browser:
    page = browser.new_page()
    page.goto("https://example.com")
    page.wait_for_timeout(5000)
    
    # Auto-detect: hcaptcha / recaptcha_v2 / turnstile / text
    ok = solver.solve_on_page(page, timeout_s=120)
    print("Solved:", ok)
```

### Manual specify type

```python
# Specify captcha type explicitly
ok = solver.solve_on_page(page, method="hcaptcha", timeout_s=120)
ok = solver.solve_on_page(page, method="recaptcha_v2", timeout_s=60)
ok = solver.solve_on_page(page, method="turnstile", timeout_s=30)
```

---

## Training Model Sendiri

### reCAPTCHA v2 Classifier

Dataset: [nobodyPerfecZ/recaptchav2-29k](https://huggingface.co/datasets/nobodyPerfecZ/recaptchav2-29k)
- 23,654 train + 2,957 validation tiles
- Labels: bicycle, bus, car, crosswalk, hydrant
- Format: Parquet (image bytes + label vector)

```bash
# 1. Download dataset
python3 -c "
from huggingface_hub import hf_hub_download
hf_hub_download('nobodyPerfecZ/recaptchav2-29k', 
                'data/train-00000-of-00001.parquet', 
                repo_type='dataset', local_dir='./data')
"

# 2. Install PyTorch (CPU-only, ~250MB)
pip install torch torchvision --index-url https://download.pytorch.org/whl/cpu
pip install pyarrow pillow scikit-learn

# 3. Edit path di training script
# Edit models/train_recaptcha.py:
# PARQUET_TRAIN = "./data/train-00000-of-00001.parquet"
# PARQUET_VAL   = "./data/validation-00000-of-00001.parquet"

# 4. Train (4 core CPU, ~2-3 jam, 8 epoch)
python3 models/train_recaptcha.py

# Output: models/recaptcha_classifier.pt (6MB)
# Best F1: ~0.9143 (bicycle=0.944, bus=0.911, car=0.821, crosswalk=0.916, hydrant=0.979)
```

### VPS Contabo (training remote)

```bash
# Di VPS Contabo (4c/7.8GB RAM, no GPU)
python3 -m venv /tmp/captcha_venv --system-site-packages
/tmp/captcha_venv/bin/pip install torch torchvision --index-url https://download.pytorch.org/whl/cpu -q
/tmp/captcha_venv/bin/pip install pyarrow pillow scikit-learn -q

PYTHONUNBUFFERED=1 /tmp/captcha_venv/bin/python -u models/train_recaptcha.py
```

### hCaptcha Classifier (future)

Dataset yang tersedia untuk hCaptcha:
- [orlov-ai/hcaptcha-dataset](https://github.com/orlov-ai/hcaptcha-dataset) — 4,068 images, 8 class (airplane, bicycle, boat, motorbus, motorcycle, seaplane, train, truck)
- [xtekky/hcaptcha-dataset](https://github.com/xtekky/hcaptcha-dataset) — 119MB, latest hCaptcha images
- [DannyLuna/recaptcha-57k-images-dataset](https://huggingface.co/datasets/DannyLuna/recaptcha-57k-images-dataset) — 57k images, berbagai class

> Training hCaptcha classifier lebih kompleks karena challenge type-nya beragam (grid selection, canvas animation, drag puzzle). Dataset orlov-ai punya 8 class yang cukup untuk grid standard.

---

## Arsitektur

```
auto-captcha-solver/
├── solver/
│   ├── vision.py               Vision LLM client (OpenAI-compatible, stream=False)
│   ├── core.py                 Dispatcher: auto-detect → route ke solver
│   ├── hcaptcha.py             hCaptcha solver (checkbox + canvas click + verify)
│   └── recaptcha_classifier.py Offline ML classifier (reCAPTCHA v2, no API)
├── server/
│   └── api.py                  2captcha-compatible HTTP API server (aiohttp)
├── models/
│   ├── recaptcha_classifier.pt Trained model (6MB, MobileNetV3-Small)
│   ├── train_log.json          Training history
│   └── train_recaptcha.py      Training script
└── USAGE.md                    Dokumentasi ini
```

### reCAPTCHA v2 Flow

```
Tile image (100x100px)
       ↓
MobileNetV3-Small (6MB, CPU ~5ms)
       ↓
{bicycle:0.02, bus:0.01, car:0.97, crosswalk:0.03, hydrant:0.01}
       ↓
match task text → click tile
```

### hCaptcha Flow

```
Page dengan hCaptcha
       ↓
Detect iframe[src*="hcaptcha"] (checkbox + challenge)
       ↓
Click checkbox → wait challenge popup (w>300, h>300)
       ↓
Scroll challenge into viewport → screenshot(full_page=False)
       ↓
Gemini vision: {"task":"click bus","grid":"3x3","cells":[2,5,7]}
       ↓
Canvas dispatchEvent(MouseEvent) di koordinat grid
       ↓
Click .button-submit via frame locator
       ↓
Poll h-captcha-response textarea / hcaptcha.getResponse()
```

---

## Known Limitations

| Issue | Status | Workaround |
|---|---|---|
| hCaptcha drag puzzle | ❌ Belum support | Skip / retry hingga dapat challenge lain |
| hCaptcha canvas animation | ⚠️ Partial | Gemini bisa baca tapi koordinat sering meleset |
| reCAPTCHA v2 image grid crop | ⚠️ Manual | Perlu implementasi crop sesuai layout target site |
| Claude via 9router | ❌ No vision | Pakai Gemini |
| IP detection | ⚠️ Perlu proxy | Wajib residential proxy (DataImpulse, dsb) |
| Rate limit hCaptcha | ⚠️ | Jeda antar attempt, rotate IP |

---

## Referensi Dataset

| Dataset | Size | Labels | URL |
|---|---|---|---|
| nobodyPerfecZ/recaptchav2-29k | 29K tiles | bicycle, bus, car, crosswalk, hydrant | [HuggingFace](https://huggingface.co/datasets/nobodyPerfecZ/recaptchav2-29k) |
| DannyLuna/recaptcha-57k | 57K images | bicycle + more | [HuggingFace](https://huggingface.co/datasets/DannyLuna/recaptcha-57k-images-dataset) |
| orlov-ai/hcaptcha-dataset | 4K images | 8 class (airplane, bicycle, boat...) | [GitHub](https://github.com/orlov-ai/hcaptcha-dataset) |
| xtekky/hcaptcha-dataset | ~119MB | Unlabeled | [GitHub](https://github.com/xtekky/hcaptcha-dataset) |

---

## Referensi Project

- [NopeCHALLC/nopecha-extension](https://github.com/NopeCHALLC/nopecha-extension) — browser extension solver (10k stars)
- [AashiqRamachandran/i-am-a-bot](https://github.com/AashiqRamachandran/i-am-a-bot) — LLM multi-agent solver
- [NoahCardoza/CaptchaHarvester](https://github.com/NoahCardoza/CaptchaHarvester) — token harvesting
- [2captcha/2captcha-python](https://github.com/2captcha/2captcha-python) — API reference untuk format compatibility
