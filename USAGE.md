# USAGE.md — Auto Captcha Solver

Self-hosted AI vision captcha solver. Uses any OpenAI-compatible vision model.
No 2captcha subscription needed.

## Quick Start

### 1. Install

```bash
pip install -r requirements.txt
camoufox fetch   # download camoufox browser
```

### 2. Configure

Set environment variables:

```bash
export VISION_BASE_URL="http://YOUR_SERVER:20128/v1"   # 9router or any OpenAI-compat endpoint
export VISION_MODEL="ag/gemini-3.8-flash-low"          # any vision-capable model
export VISION_API_KEY="sk-..."
```

Or pass directly when instantiating `VisionClient`.

> ⚠️ **Important for 9router**: 9router returns SSE by default.
> The solver automatically adds `"stream": False` to all requests.

### 3. Use as Python library

```python
from camoufox.sync_api import Camoufox
from solver.vision import VisionClient
from solver.hcaptcha import HcaptchaSolver

PROXY = {
    "server": "http://gw.dataimpulse.com:823",
    "username": "YOUR_USER",
    "password": "YOUR_PASS"
}

vision = VisionClient(
    base_url="http://169.58.180.111:20128/v1",
    model="ag/gemini-3.8-flash-low",
    api_key="sk-..."
)
solver = HcaptchaSolver(vision)

with Camoufox(headless=False, proxy=PROXY, humanize=False, geoip=True) as browser:
    page = browser.new_page()
    page.goto("https://example.com/with-hcaptcha")
    page.wait_for_timeout(5000)
    
    ok = solver.solve(page, timeout_s=120)
    print("Solved:", ok)
```

### 4. Use as 2captcha-compatible API server

```bash
python -m server.api --port 8080
```

Then call it like 2captcha:

```bash
# Submit job
curl -X POST http://localhost:8080/in.php \
  -H "Content-Type: application/json" \
  -d '{"method":"hcaptcha","sitekey":"...","pageurl":"https://...","key":"demo"}'
# Returns: {"status":1,"request":"job_id_here"}

# Poll result
curl "http://localhost:8080/res.php?action=get&id=job_id_here"
# Returns: {"status":1,"request":"P1_token..."} when ready
# Returns: {"status":0,"request":"CAPCHA_NOT_READY"} while solving
```

## Supported Captcha Types

| Type | Status | Notes |
|------|--------|-------|
| hCaptcha image grid | ✅ Working | vision identifies tiles, clicks via frame locator |
| hCaptcha checkbox | ✅ Working | auto-click checkbox iframe |
| reCAPTCHA v2 | ⚙️ Skeleton | checkbox click only, no image grid yet |
| Cloudflare Turnstile | ⚙️ Skeleton | checkbox click relay |
| Text CAPTCHA | ⚙️ Skeleton | OCR via vision |

## Architecture

```
solver/
  vision.py     — OpenAI-compatible vision client (stream=False fix for 9router)
  hcaptcha.py   — hCaptcha solver (checkbox + grid via div.option frame locator)
  core.py       — dispatcher: auto-detect captcha type, route to solver
server/
  api.py        — 2captcha-compatible HTTP API server (aiohttp)
```

## How hCaptcha Solving Works

1. **Detect** — find `iframe[src*="hcaptcha"]`
2. **Checkbox** — click checkbox iframe to trigger challenge
3. **Wait** — poll until challenge iframe expands (`w>300, h>300`)
4. **Scroll** — scroll challenge into viewport
5. **Screenshot** — `page.screenshot(full_page=False)`
6. **Vision** — send screenshot to vision model with task prompt
7. **Click** — JS click `div.option[N]` inside challenge frame
8. **Verify** — click `.button-submit` inside challenge frame
9. **Check** — poll `textarea[name="h-captcha-response"]` or `hcaptcha.getResponse()`

## Vision Prompt

The solver sends this prompt to the vision model:

```
You are solving an hCaptcha challenge image grid. Study the screenshot carefully.

STEP 1: Find the task instruction text (at the top of the challenge popup window).
STEP 2: Count all image tiles in the grid (usually 3x3=9 tiles, but can be different).
STEP 3: Look at EACH tile carefully and identify which ones satisfy the task.
STEP 4: Number tiles LEFT→RIGHT, TOP→BOTTOM starting from 0.

Return ONLY JSON:
{"task": "exact task text", "grid": "3x3", "cells": [2]}
```

## Proxy

Required for most captcha providers. Tested with DataImpulse residential:

```python
PROXY = {
    "server": "http://gw.dataimpulse.com:823",  # :823 = rotating (IP/req)
    "username": "user__cr.id",                    # cr.id = Indonesia exit
    "password": "pass"
}
# pass geoip=True to Camoufox for proper IP geolocation
```

## Vision Model Recommendations

| Model | Accuracy | Speed | Notes |
|-------|----------|-------|-------|
| `ag/gemini-3.8-flash-low` | ⭐⭐⭐ | Fast | Best balance |
| `ag/gemini-3.8-flash-high` | ⭐⭐⭐⭐ | Slower | Higher accuracy |
| `ag/claude-sonnet-4-6` | ⭐⭐⭐⭐⭐ | Slow | Best accuracy |

## Dataset

Training/evaluation dataset: [nobodyPerfecZ/recaptchav2-29k](https://huggingface.co/datasets/nobodyPerfecZ/recaptchav2-29k)
- 23,654 train / 2,957 test images
- Multi-label: bicycle, bus, car, fire hydrant, motorcycle, traffic light, etc.

## Known Limitations

1. **Vision accuracy** depends on model — complex tasks (jump height comparison) need stronger models
2. **hCaptcha canvas challenges** — some challenge types use canvas animation, harder to click
3. **Proxy required** — direct IP flagged by hCaptcha/reCAPTCHA
4. **Rate limiting** — solve too fast = ban; built-in delays mitigate this

## References

- [NopeCHALLC/nopecha-extension](https://github.com/NopeCHALLC/nopecha-extension) — DOM selectors reference
- [AashiqRamachandran/i-am-a-bot](https://github.com/AashiqRamachandran/i-am-a-bot) — Multi-modal LLM agent approach
- [NoahCardoza/CaptchaHarvester](https://github.com/NoahCardoza/CaptchaHarvester) — Token harvesting approach
- Real hCaptcha solving experience (Fireworks.ai billing, 2026)
