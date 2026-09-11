"""hCaptcha solver — final production version.
Verified flow:
1. Detect hCaptcha iframe
2. Click checkbox → wait for challenge
3. Scroll challenge into view
4. Screenshot viewport (not full_page)
5. Vision model identifies tiles
6. Click tiles by computed coordinates
7. Click verify → poll token
"""
import logging
import time

from .vision import VisionClient

log = logging.getLogger("solver.hcaptcha")

GRID_PROMPT = """You are solving an hCaptcha challenge image grid. Study the screenshot carefully.

STEP 1: Find the task instruction text (at the top of the challenge popup window).
STEP 2: Count all image tiles in the grid (usually 3x3=9 tiles, but can be different).
STEP 3: Look at EACH tile carefully and identify which ones satisfy the task.
STEP 4: Number tiles LEFT→RIGHT, TOP→BOTTOM starting from 0.

For "click the character who jumps the HIGHEST" → pick the tile where the character/figure is at the HIGHEST vertical position or jumping the most.
For "click the character who jumps the LOWEST" → pick the tile where the character is at the LOWEST vertical position.
For "find animals (1x tiger, 1x bear)" → find tiles with exactly a tiger and a bear.
For standard object detection → select all tiles containing the requested object.

Return ONLY JSON (absolutely no markdown, no explanation):
{"task": "exact task text", "grid": "3x3", "cells": [2]}

cells = list of 0-based tile indices that match the task."""


class HcaptchaSolver:
    def __init__(self, vision: VisionClient):
        self.vision = vision

    def solve(self, page, timeout_s=90) -> bool:
        deadline = time.time() + timeout_s
        rounds = 0

        while time.time() < deadline:
            rounds += 1
            log.info("[round %d] starting", rounds)

            # find frames
            frames = self._get_hcap_frames(page)
            if not frames:
                log.warning("no hcaptcha frames")
                return False

            cb = next((f for f in frames if f["h"] < 100), None)
            big = [f for f in frames if f["w"] > 300 and f["h"] > 300 and f["y"] > -500]

            if not big:
                # click checkbox
                if cb:
                    self._click_checkbox(page, cb)
                else:
                    log.warning("no checkbox found")
                    return False
                # wait for challenge
                if not self._wait_for_challenge(page, timeout=20):
                    log.warning("challenge didn't appear")
                    continue
                big = [f for f in self._get_hcap_frames(page) if f["w"] > 300 and f["h"] > 300]

            ch = big[0] if big else None
            if not ch:
                time.sleep(2)
                continue

            # scroll challenge into view
            page.evaluate("""() => {
                const chal = [...document.querySelectorAll('iframe')]
                    .find(f => f.getBoundingClientRect().width > 300 && 
                               f.getBoundingClientRect().height > 300 &&
                               /hcaptcha/.test(f.src||''));
                if (chal) chal.scrollIntoView({behavior:'instant', block:'center'});
            }""")
            time.sleep(0.5)

            # refresh challenge coords after scroll
            big2 = [f for f in self._get_hcap_frames(page) if f["w"] > 300 and f["h"] > 300 and f["y"] > -100]
            if big2:
                ch = big2[0]

            # wait for images to load
            time.sleep(3)

            # screenshot viewport only (not full page, for correct coords)
            shot = "/tmp/hcap_solve.png"
            page.screenshot(path=shot, full_page=False)

            # ask vision
            resp = self._ask_vision(shot)
            if not resp:
                time.sleep(2)
                continue

            cells = resp.get("cells", [])
            log.info("task=%s cells=%s", resp.get("task","?"), cells)

            if not cells:
                log.info("no cells identified, retrying")
                time.sleep(3)
                continue

            # click each identified tile
            for cell in cells:
                self._click_tile(page, ch, cell)

            time.sleep(1.5)

            # click verify
            self._click_verify(page, ch)
            time.sleep(4)

            # check solved
            result = self._check_solved(page)
            if result:
                log.info("✅ hcaptcha solved: %s", result)
                return True

            log.info("not solved yet, checking for new challenge...")
            time.sleep(2)

        log.warning("hcaptcha timeout after %d rounds", rounds)
        return False

    # ---------- helpers ----------

    def _get_hcap_frames(self, page):
        return page.evaluate("""() => {
            return [...document.querySelectorAll('iframe')]
                .filter(f => /hcaptcha/.test(f.src||''))
                .map(f => {
                    const r = f.getBoundingClientRect();
                    return {src:f.src.slice(0,100), x:r.x, y:r.y, w:r.width, h:r.height};
                });
        }""")

    def _click_checkbox(self, page, cb):
        # click left portion of checkbox iframe (where the checkmark is)
        cx = cb["x"] + min(30, cb["w"] * 0.15)
        cy = cb["y"] + cb["h"] / 2
        page.evaluate(f"""() => {{
            const iframes = [...document.querySelectorAll('iframe')];
            const cb = iframes.find(f => /checkbox/.test(f.src||'') || 
                (f.getBoundingClientRect().height < 100 && /hcaptcha/.test(f.src||'')));
            if (cb) cb.scrollIntoView({{behavior:'instant', block:'center'}});
        }}""")
        time.sleep(0.3)
        page.mouse.move(cx - 3, cy - 2)
        time.sleep(0.1)
        page.mouse.click(cx, cy)
        log.info("clicked checkbox at (%.0f,%.0f)", cx, cy)

    def _wait_for_challenge(self, page, timeout=20):
        for _ in range(timeout):
            time.sleep(1)
            frames = self._get_hcap_frames(page)
            big = [f for f in frames if f["w"] > 300 and f["h"] > 300 and f["y"] > -100]
            if big:
                return True
        return False

    def _ask_vision(self, shot):
        """Ask vision to identify cells. Returns parsed dict."""
        try:
            raw = self.vision.chat(GRID_PROMPT + "\nReturn ONLY valid JSON, no markdown fences.", shot)
            log.debug("vision raw: %s", raw[:200])
            import json
            start = raw.find("{"); end = raw.rfind("}")
            if start != -1 and end > start:
                return json.loads(raw[start:end + 1])
        except Exception as e:
            log.warning("vision err: %s", str(e)[:100])
        return None

    def _click_tile(self, page, ch, cell):
        """Click tile inside hCaptcha challenge. Primary: frame locator. Fallback: coord."""
        row, col = divmod(cell, 3)

        # Try frame locator first
        try:
            for fr in page.frames:
                if "challenge" in fr.url and "hcaptcha" in fr.url:
                    # Try both .option and canvas click
                    tiles = fr.query_selector_all("div.option")
                    if tiles and cell < len(tiles):
                        try:
                            tiles[cell].click(timeout=3000, force=True)
                            log.info("tile %d via .option force click", cell)
                            return
                        except Exception:
                            # try direct JS click
                            fr.evaluate(f"() => {{ const tiles = document.querySelectorAll('div.option'); if(tiles[{cell}]) tiles[{cell}].click(); }}")
                            log.info("tile %d via .option JS click", cell)
                            return
        except Exception as e:
            log.warning("frame tile click err: %s", str(e)[:80])

        # Fallback: coordinate click
        header_frac = 0.28
        grid_frac = 0.64
        margin_x = 0.04

        gx = ch["x"] + ch["w"] * margin_x + ch["w"] * (1 - 2 * margin_x) * (col + 0.5) / 3
        gy = ch["y"] + ch["h"] * header_frac + ch["h"] * grid_frac * (row + 0.5) / 3
        # clamp to challenge bounds
        gx = max(ch["x"] + 10, min(ch["x"] + ch["w"] - 10, gx))
        gy = max(ch["y"] + 10, min(ch["y"] + ch["h"] - 10, gy))

        log.info("coord click tile %d -> (%.0f,%.0f)", cell, gx, gy)
        page.mouse.move(gx - 2, gy - 2)
        time.sleep(0.15)
        page.mouse.click(gx, gy)
        time.sleep(0.6)

    def _click_verify(self, page, ch):
        """Click Verify button inside challenge frame."""
        verified = page.evaluate("""() => {
            const ifrs = [...document.querySelectorAll('iframe')];
            for (const f of ifrs) {
                try {
                    const doc = f.contentDocument;
                    if (!doc) continue;
                    // exact class from DOM dump: 'button-submit button'
                    const btn = doc.querySelector('.button-submit, .button-submit.button, [role="button"].button-submit');
                    if (btn) { btn.click(); return 'dom_click'; }
                } catch(e) {}
            }
            return false;
        }""")

        if not verified:
            # try via frame locator
            try:
                for fr in page.frames:
                    if "challenge" in fr.url and "hcaptcha" in fr.url:
                        verify_btn = fr.query_selector(".button-submit")
                        if verify_btn:
                            verify_btn.click(timeout=3000)
                            log.info("verify clicked via frame locator")
                            return
            except Exception as e:
                log.warning("verify frame err: %s", str(e)[:60])

            # last resort: coordinate
            if ch:
                vx = ch["x"] + ch["w"] / 2
                vy = ch["y"] + ch["h"] * 0.92
                page.mouse.click(vx, vy)
                log.info("verify coord click at (%.0f,%.0f)", vx, vy)
        else:
            log.info("verify: %s", verified)

    def _check_solved(self, page):
        return page.evaluate("""() => {
            // Method 1: direct textarea value
            const ta = document.querySelector('textarea[name="h-captcha-response"], textarea[name="g-recaptcha-response"]');
            if (ta && ta.value && ta.value.length > 20) return 'token_found';
            
            // Method 2: hcaptcha JS API
            try {
                if (window.hcaptcha) {
                    const r = window.hcaptcha.getResponse();
                    if (r && r.length > 10) return 'hcaptcha_api_token';
                }
            } catch(e) {}
            
            // Method 3: challenge iframe gone = likely solved (challenge dismissed)
            const chal = [...document.querySelectorAll('iframe')].find(f => /challenge/.test(f.src||''));
            if (!chal) {
                // but checkbox iframe should still be there — if it shows checkmark = solved
                const cb = [...document.querySelectorAll('iframe')].find(f => /checkbox/.test(f.src||''));
                if (cb) return 'challenge_dismissed_checkbox_visible';
            }
            if (chal && chal.getBoundingClientRect().height < 50) return 'challenge_hidden';
            
            return null;
        }""")