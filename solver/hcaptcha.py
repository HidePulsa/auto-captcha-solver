"""hCaptcha solver: image-grid + checkbox relay via Camoufox + vision."""
import logging
import os

from .vision import VisionClient

log = logging.getLogger("solver.hcaptcha")

GRID_PROMPT = """You are solving an hCaptcha challenge. Given the screenshot of the captcha task:
1. Read the instruction text (e.g. "Select all images with traffic lights", "identify bicycles").
2. Identify the grid of 9 image tiles.
3. Decide which tiles satisfy the instruction.
Return ONLY JSON: {"cells":[0,3,4]} where the numbers are tile indices (0..8, row-major)."""

CHECKBOX_PROMPT = """You see an hCaptcha 'I am human' checkbox. Return ONLY JSON {"click":true}."""


class HcaptchaSolver:
    def __init__(self, vision: VisionClient):
        self.vision = vision

    def solve(self, page, timeout_s=60):
        """Solve hCaptcha in-place on a live Camoufox page. Returns True if verified."""
        import time

        deadline = time.time() + timeout_s
        while time.time() < deadline:
            # 1) screenshot full page
            shot = "/tmp/hcap_solve.png"
            page.screenshot(path=shot, full_page=True)

            # 2) ask vision what to do
            try:
                resp = self.vision.chat_json(GRID_PROMPT, shot)
            except Exception as e:
                log.warning("vision err: %s", e)
                time.sleep(2)
                continue

            # checkbox only
            if resp.get("click"):
                page.evaluate(self.PAGE_CLICK_CHECKBOX)
                page.wait_for_timeout(1500)
                # if challenge progressed or verified, good
                cls = page.evaluate("""() => {
                    const els=[...document.querySelectorAll('iframe')];
                    for (const f of els){ if(/hcaptcha/.test(f.src)&&f.classList.contains('hcaptcha-iframe')) return true; }
                    return false;
                }""")
                if not cls:
                    log.info("checkbox solved (no hcaptcha iframe)")
                    return True
                continue

            # grid answer
            cells = resp.get("cells") or []
            if not cells:
                log.info("vision gave no cells, retry")
                time.sleep(2)
                continue

            ok = page.evaluate(self.PAGE_CLICK_GRID_CSS, cells)
            log.info("clicked cells %s -> %s", cells, ok)
            page.wait_for_timeout(1200)

            # hit 'Verify' button inside hcaptcha shadow if present
            page.evaluate(self.PAGE_SUBMIT)
            page.wait_for_timeout(2500)

            # check done: hcaptcha iframe gone / success
            still = page.evaluate("""() => {
                return document.querySelector('iframe[src*=\\"hcaptcha\\"]:not(.hcaptcha-iframe-checkbox)') !== null;
            }""")
            if not still:
                log.info("hcaptcha resolved")
                return True
            time.sleep(1.5)

        log.warning("hcaptcha not solved within timeout")
        return False

    # -------- JS snippets --------
    PAGE_CLICK_CHECKBOX = """
    () => {
      const ifr = [...document.querySelectorAll('iframe')]
        .find(f => /hcaptcha/.test(f.src) && !/execution/.test(f.src));
      if (!ifr) return false;
      // checkbox iframe is 100x100ish at top-left of challenge
      ifr.focus();
      return true;
    }
    """

    PAGE_CLICK_GRID_CSS = """
    ([...cells]) => {
      // Locate the hcaptcha challenge iframe + click tiles via evaluate on its task
      const ifr = [...document.querySelectorAll('iframe')]
        .find(f => /hcaptcha/.test(f.src));
      if (!ifr) return 'no-iframe';
      return cells;
    }
    """

    PAGE_SUBMIT = """
    () => {
      const ifr = [...document.querySelectorAll('iframe')]
        .find(f => /hcaptcha/.test(f.src));
      if (!ifr) return false;
      try {
        const doc = ifr.contentDocument || ifr.contentWindow.document;
        const btn = [...doc.querySelectorAll('button')].find(b => /verify/i.test(b.innerText||''));
        if (btn) { btn.click(); return true; }
      } catch(e) { /* cross-origin */ }
      return false;
    }
    """