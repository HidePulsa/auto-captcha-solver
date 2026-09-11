# Auto-Captcha-Solver

AI vision-powered CAPTCHA solver — self-hosted substitute for 2captcha.
Solves **reCAPTCHA v2/v3, hCaptcha, Turnstile, Cloudflare, Text** using a vision LLM
(MCN/OpenAI/Gemini) + Camoufox browser automation.

> Inspired by `NoahCardoza/CaptchaHarvester`, `AashiqRamachandran/i-am-a-bot`,
> and lessons from real hCaptcha grid-solving in training.

## Quickstart

```bash
pip install -r requirements.txt
python -m server.api --port 8080
```

Then POST captcha jobs (2captcha-compatible):

```bash
curl -X POST http://localhost:8080/in.php \
  -H "Content-Type: application/json" \
  -d '{"method":"hcaptcha","sitekey":"...","pageurl":"https://example.com","key":"YOUR_CLIENT_KEY"}'
```

## Supported

| Captcha | Method | Strategy |
|---|---|---|
| hCaptcha image grid | `hcaptcha` | Vision-model grid answer → Camoufox clicks |
| hCaptcha checkbox | `hcaptcha` | Invisible-checkbox relay |
| reCAPTCHA v2 checkbox | `userrecaptcha` | Human checkbox click |
| reCAPTCHA v3 token | `recaptcha_v3` | token relay |
| Turnstile | `turnstile` | token extraction |
| Text | `text` | Vision OCR |

## Vision Backend (config in `solver/config.py`)

Set env vars:

```bash
export VISION_BASE_URL="http://127.0.0.1:20128/v1"   # MCN/9router example
export VISION_MODEL="mcn/deepseek-v4-flash-vision-exp"
export VISION_API_KEY="sk-..."
export CAMOUFOX_HEADLESS="false"
```

## Architecture

```
solver/
  core.py          — detect type → route → verify loop
  vision.py        — vision model wrapper
  hcaptcha.py      — grid + checkbox solvers
  recaptcha_v2.py
  recaptcha_v3.py
  turnstile.py
  text.py
  utils.py         — proxy, screenshot, coordinate math
server/
  api.py           — 2captcha-compatible HTTP API (/in.php, /res.php)
tests/
sample_captchas/
```

## License
MIT