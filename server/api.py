"""2captcha-compatible HTTP API server.

Endpoints:
  POST /in.php  — submit captcha job, returns id
  POST /res.php — fetch result by id
"""
import argparse, asyncio, json, logging, os, time, uuid

from aiohttp import web

from ..solver.core import Solver
from ..solver.vision import VisionClient

log = logging.getLogger("server.api")

JOBS: dict[str, dict] = {}  # id -> {"status","result","created"}


async def handle_in(request):
    data = await request.post() if request.content_type.startswith("multipart") else await request.json()
    method = data.get("method", "hcaptcha")
    key = data.get("key", "demo")
    sitekey = data.get("sitekey", "")
    pageurl = data.get("pageurl", "")
    job_id = uuid.uuid4().hex[:12]

    JOBS[job_id] = {"status": "processing", "result": None, "created": time.time()}

    # Fire and forget — client polls /res.php
    asyncio.create_task(_solve_worker(job_id, method, sitekey, pageurl, key))

    return web.json_response({"status": 1, "request": job_id})


async def handle_res(request):
    action = request.query.get("action", "get")
    job_id = request.query.get("id", "")
    job = JOBS.get(job_id)
    if not job:
        return web.json_response({"status": 0, "request": "ERROR_NO_SUCH_CAPTCHA_ID"})
    if action == "get":
        if job["status"] == "ready":
            return web.json_response({"status": 1, "request": job["result"]})
        return web.json_response({"status": 0, "request": "CAPCHA_NOT_READY"})
    return web.json_response({"status": 0, "request": "ERROR_WRONG_USER_KEY"})


async def _solve_worker(job_id: str, method: str, sitekey: str, pageurl: str, key: str):
    """Heavy lifting: open Camoufox, navigate, solve, store result."""
    from camoufox.sync_api import Camoufox
    proxy = os.getenv("PROXY", "")
    extra = {"proxy": {"server": proxy}} if proxy else {}

    try:
        vision = VisionClient()
        solver = Solver(vision)
        with Camoufox(headless=False, **extra) as browser:
            p = browser.new_page()
            p.goto(pageurl, wait_until="domcontentloaded", timeout=30000)
            p.wait_for_timeout(3000)
            ok = solver.solve_on_page(p, method=method, timeout_s=120)
            if ok:
                # Try to extract token for token-based methods
                token = p.evaluate("""() => {
                    const ta = document.querySelector('textarea[data-hcaptcha], textarea.g-recaptcha-response, #cf-turnstile-response');
                    return ta ? ta.value : 'ok';
                }""")
                JOBS[job_id].update({"status": "ready", "result": token or "ok"})
            else:
                JOBS[job_id].update({"status": "ready", "result": "ERROR_CAPTCHA_UNSOLVABLE"})
    except Exception as e:
        log.error("solve worker error: %s", e)
        JOBS[job_id].update({"status": "ready", "result": f"ERROR_{e}"})


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=8080)
    parser.add_argument("--host", default="0.0.0.0")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO)

    app = web.Application()
    app.router.add_post("/in.php", handle_in)
    app.router.add_get("/res.php", handle_res)

    log.info("Starting Captcha Solver server on %s:%s", args.host, args.port)
    web.run_app(app, host=args.host, port=args.port)


if __name__ == "__main__":
    main()