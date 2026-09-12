"""
reCAPTCHA v2 tile classifier — offline inference.
Trained on nobodyPerfecZ/recaptchav2-29k (23,654 tiles, MobileNetV3-Small).
F1 macro: 0.9143 | bicycle=0.944, bus=0.911, car=0.821, crosswalk=0.916, hydrant=0.979

Usage:
    clf = ReCaptchaClassifier()
    # single tile
    result = clf.predict_tile("tile.png")   # {"bicycle":0.02,"bus":0.01,"car":0.97,...}
    # batch of tiles
    results = clf.predict_batch(["t0.png","t1.png",...])
    # solve: given task text + list of tile image paths, return which cells to click
    cells = clf.solve("Select all images with cars", tile_paths)  # [1,4,7]
"""
import os
import io
from pathlib import Path
from typing import Optional

import torch
import torch.nn as nn
from torchvision import models, transforms
from PIL import Image

LABELS = ["bicycle", "bus", "car", "crosswalk", "hydrant"]
MODEL_PATH = Path(__file__).parent.parent / "models" / "recaptcha_classifier.pt"

# task text → label keyword mapping
TASK_LABEL_MAP = {
    "bicycle": "bicycle",
    "bike":    "bicycle",
    "bus":     "bus",
    "car":     "car",
    "vehicle": "car",
    "automobile": "car",
    "crosswalk": "crosswalk",
    "pedestrian crossing": "crosswalk",
    "zebra crossing": "crosswalk",
    "fire hydrant": "hydrant",
    "hydrant": "hydrant",
}

TRANSFORM = transforms.Compose([
    transforms.Resize((112, 112)),
    transforms.ToTensor(),
    transforms.Normalize([0.485, 0.456, 0.406], [0.229, 0.224, 0.225]),
])


def _build_model(num_classes=5):
    m = models.mobilenet_v3_small(weights=None)
    m.classifier[3] = nn.Linear(m.classifier[3].in_features, num_classes)
    return m


class ReCaptchaClassifier:
    def __init__(self, model_path: Optional[str] = None, threshold: float = 0.5):
        path = Path(model_path) if model_path else MODEL_PATH
        self.threshold = threshold
        self.device = torch.device("cpu")
        self.model = _build_model(5).to(self.device)
        ckpt = torch.load(path, map_location="cpu", weights_only=True)
        self.model.load_state_dict(ckpt["model_state"])
        self.model.eval()
        self.labels = ckpt.get("labels", LABELS)
        self.threshold = ckpt.get("threshold", threshold)

    def predict_tile(self, img_input) -> dict:
        """Predict labels for a single tile.
        img_input: file path str, PIL.Image, or bytes.
        Returns {label: probability} dict.
        """
        img = self._load_img(img_input)
        tensor = TRANSFORM(img).unsqueeze(0).to(self.device)
        with torch.no_grad():
            logits = self.model(tensor)
            probs  = torch.sigmoid(logits).squeeze().tolist()
        return {self.labels[i]: round(probs[i], 4) for i in range(len(self.labels))}

    def predict_batch(self, img_inputs: list) -> list[dict]:
        """Predict labels for a list of tiles. Returns list of dicts."""
        tensors = []
        for inp in img_inputs:
            img = self._load_img(inp)
            tensors.append(TRANSFORM(img))
        batch = torch.stack(tensors).to(self.device)
        with torch.no_grad():
            logits = self.model(batch)
            probs  = torch.sigmoid(logits).cpu().tolist()
        return [{self.labels[i]: round(p[i], 4) for i in range(len(self.labels))} for p in probs]

    def solve(self, task_text: str, tile_inputs: list) -> list[int]:
        """Given task text + tile images, return indices of tiles to click.
        
        task_text: e.g. "Select all images with a fire hydrant"
        tile_inputs: list of file paths, PIL.Images, or bytes (one per tile)
        Returns: list of 0-based tile indices to click
        """
        label = self._extract_label(task_text)
        if label is None:
            return []  # unsupported task → fallback to vision LLM

        preds = self.predict_batch(tile_inputs)
        return [i for i, p in enumerate(preds) if p.get(label, 0) >= self.threshold]

    def _extract_label(self, task_text: str) -> Optional[str]:
        """Map task text to a label name."""
        task_lower = task_text.lower()
        for kw, label in TASK_LABEL_MAP.items():
            if kw in task_lower:
                return label
        return None

    @staticmethod
    def _load_img(inp) -> Image.Image:
        if isinstance(inp, (str, Path)):
            return Image.open(inp).convert("RGB")
        if isinstance(inp, bytes):
            return Image.open(io.BytesIO(inp)).convert("RGB")
        if isinstance(inp, Image.Image):
            return inp.convert("RGB")
        raise ValueError(f"unsupported input type: {type(inp)}")
