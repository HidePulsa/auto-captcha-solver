"""Core dispatcher — detect captcha type, route to solver, verify loop."""
import logging

from .hcaptcha import HcaptchaSolver
from .vision import VisionClient

log = logging.getLogger("solver.core")


class Solver:
    def __init__(self, vision: VisionClient):
        self.vision = vision
        self.hcaptcha = HcaptchaSolver(vision)

    def solve_on_page(self, page, method: str = None, **kwargs) -> bool:
        """Solve the captcha visible on a live browser page.

        method: 'hcaptcha' | 'recaptcha_v2' | 'recaptcha_v3' | 'turnstile' | 'text'
                If None, we auto-detect from DOM.
        """
        if method is None:
            method = self._detect(page)
            log.info("auto-detected captcha: %s", method)

        if method == "hcaptcha":
            return self.hcaptcha.solve(page, timeout_s=kwargs.get("timeout_s", 60))
        if method == "recaptcha_v2":
            return self._solve_checkbox_class(page, "g-recaptcha")
        if method == "turnstile":
            return self._solve_checkbox_class(page, "cf-turnstile")
        if method == "text":
            return self._solve_text(page)
        raise ValueError(f"unsupported method: {method}")

    def _detect(self, page) -> str:
        """DOM sniff for captcha type."""
        return page.evaluate("""() => {
            if (document.querySelector('iframe[src*="hcaptcha"]')) return 'hcaptcha';
            if (document.querySelector('.g-recaptcha, iframe[src*="recaptcha"]')) return 'recaptcha_v2';
            if (document.querySelector('.cf-turnstile, iframe[src*="turnstile"]')) return 'turnstile';
            if (document.querySelector('input[name*="captcha"], #captcha, .captcha-image')) return 'text';
            return 'unknowntype';
        }""")

    def _solve_checkbox_class(self, page, selector_css: str) -> bool:
        """Generic checkbox/relay solver for recaptcha/turnstile styled checkboxes."""
        return page.evaluate(f"""() => {{
            const box = document.querySelector('{selector_css}');
            if (!box) return false;
            box.scrollIntoView({{behavior:'instant',block:'center'}});
            box.click();
            return true;
        }}""")

    def _solve_text(self, page) -> bool:
        """OCR a text captcha via vision and type the answer."""
        import tempfile, os
        shot = os.path.join(tempfile.gettempdir(), "text_captcha.png")
        page.evaluate("""() => {
            const img = document.querySelector('.captcha-image, #captcha, img[alt*="captcha" i]');
            if (img) img.scrollIntoView({behavior:'instant',block:'center'});
        }""")
        page.screenshot(path=shot, full_page=False)
        txt = self.vision.chat("Read the CAPTCHA text. Return ONLY the characters.", shot)
        filled = page.evaluate("""(ans) => {
            const inp = document.querySelector('input[name*="captcha"], #captcha, input[type="text"].captcha');
            if (!inp) return false;
            Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype,'value').set.call(inp, ans);
            inp.dispatchEvent(new Event('input',{bubbles:true}));
            inp.dispatchEvent(new Event('change',{bubbles:true}));
            return true;
        }""", txt)
        return bool(filled)