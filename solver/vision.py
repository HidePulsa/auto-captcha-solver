"""Vision model wrapper — talks to any OpenAI-compatible vision endpoint (MCN/9router/OpenAI/Gemini)."""
import base64
import json
import os
import time
import httpx


class VisionError(Exception):
    pass


class VisionClient:
    """Minimal OpenAI-compatible vision client with auth + retry."""

    def __init__(self, base_url=None, model=None, api_key=None, timeout=120):
        self.base_url = (base_url or os.getenv("VISION_BASE_URL", "http://127.0.0.1:20128/v1")).rstrip("/")
        self.model = model or os.getenv("VISION_MODEL", "mcn/deepseek-v4-flash-vision-exp")
        self.api_key = api_key or os.getenv("VISION_API_KEY", "")
        self.timeout = timeout
        self._http = httpx.Client(timeout=timeout)

    # ---------- image helpers ----------
    @staticmethod
    def img_url_from_file(path: str) -> str:
        with open(path, "rb") as f:
            b64 = base64.b64encode(f.read()).decode()
        return f"data:image/png;base64,{b64}"

    # ---------- main call ----------
    def chat(self, prompt: str, image_path: str | None = None) -> str:
        content = [{"type": "text", "text": prompt}]
        if image_path:
            content.append({"type": "image_url", "image_url": {"url": self.img_url_from_file(image_path)}})
        payload = {
            "model": self.model,
            "messages": [{"role": "user", "content": content}],
            "temperature": 0.0,
            "stream": False,  # 9router returns SSE by default — force non-stream
        }
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"

        for attempt in range(3):
            try:
                r = self._http.post(f"{self.base_url}/chat/completions", json=payload, headers=headers)
                r.raise_for_status()
                return r.json()["choices"][0]["message"]["content"].strip()
            except Exception as e:
                if attempt == 2:
                    raise VisionError(f"vision call failed: {e}")
                time.sleep(2 * (attempt + 1))

    def chat_json(self, prompt: str, image_path: str | None = None) -> dict:
        """Ask model to return strict JSON; parse tolerant."""
        out = self.chat(prompt + "\nReturn ONLY valid JSON, no markdown.", image_path)
        out = out.strip()
        if out.startswith("```"):
            out = out.split("```", 2)[1].strip()
        # cari FIRST { ... } block (model kadang nambah teks setelah json)
        start = out.find("{")
        end = out.rfind("}")
        if start != -1 and end > start:
            block = out[start:end + 1]
            try:
                return json.loads(block)
            except json.JSONDecodeError:
                pass
        # fallback: raw_parse
        raise VisionError(f"could not parse JSON from: {out[:200]}")