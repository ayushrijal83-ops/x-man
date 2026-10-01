"""Vision analysis (M06): zero-shot photo classification for citizen reports.

Model: google/siglip-base-patch16-224 (Apache-2.0), pretrained by Google, loaded from
local files only. X-MAN did not train or fine-tune it. The image is compared against
fixed text prompts; the softmax over all prompts is summed per class:

    road_damage | landslide | other (normal road, building, person, sky, ...)

The best hazard class wins only if its share is >= VISION_CONFIDENCE_THRESHOLD,
otherwise the result is 'unknown'. `confidence` is that share: a relative score
against this prompt set, not a calibrated probability that the hazard exists.

Evidence only: this module takes image bytes and returns a VisionResult. It has no
access to paths, reports, Incidents, severity or notifications.
"""
import io
import os
import threading
from dataclasses import dataclass

from flask import current_app
from PIL import Image

# torch only: stop transformers from importing TensorFlow (a broken TF install would break loading).
# Set at import time so it is in place before anything imports transformers.
os.environ.setdefault('USE_TF', '0')

HAZARD_LABELS = ('road_damage', 'landslide')
UNKNOWN = 'unknown'

# Prompts were picked by hand and checked on a few dozen public photos; not a validated taxonomy.
PROMPTS = {
    'road_damage': ['a road with potholes', 'a cracked and broken asphalt road',
                    'a road that has collapsed or been washed away', 'a damaged road surface'],
    'landslide': ['a landslide', 'rocks and mud from a landslide blocking a road',
                  'a collapsed hillside with soil and debris', 'a mudslide'],
    'other': ['an intact paved road', 'a normal street', 'a building', 'a collapsed building', 'a person',
              'an animal', 'the sky', 'food', 'an indoor room', 'a forest', 'a mountain landscape',
              'a river', 'a painting'],
}


class VisionError(Exception):
    """Analysis could not run: model missing/unloadable, undecodable image, or inference error.
    Messages are safe to log; they never contain paths or image data."""


@dataclass(frozen=True)
class VisionResult:
    label: str  # 'road_damage' | 'landslide' | 'unknown'
    confidence: float  # share of the best hazard class, 0..1
    model: str
    model_version: str


class SiglipClassifier:
    """The real model. Loaded once per process; text prompts are embedded at load time."""

    def __init__(self, path):
        import torch
        from transformers import AutoModel, AutoProcessor

        self.torch = torch
        self.model = AutoModel.from_pretrained(path, local_files_only=True).eval()
        self.processor = AutoProcessor.from_pretrained(path, local_files_only=True, use_fast=False)
        self.groups = [group for group, prompts in PROMPTS.items() for _ in prompts]
        texts = [f'This is a photo of {p}.' for prompts in PROMPTS.values() for p in prompts]
        with torch.no_grad():
            inputs = self.processor(text=texts, padding='max_length', return_tensors='pt')
            text = self.model.get_text_features(**inputs)
            self.text = text / text.norm(dim=-1, keepdim=True)

    def scores(self, image):
        """PIL RGB image -> {'road_damage': p, 'landslide': p, 'other': p}, summing to 1."""
        with self.torch.no_grad():
            features = self.model.get_image_features(**self.processor(images=image, return_tensors='pt'))
            features = features / features.norm(dim=-1, keepdim=True)
            logits = (features @ self.text.T)[0] * self.model.logit_scale.exp() + self.model.logit_bias
            probs = logits.softmax(dim=0).tolist()
        totals = dict.fromkeys(PROMPTS, 0.0)
        for group, p in zip(self.groups, probs):
            totals[group] += p
        return totals


_classifier = None
# ponytail: one global lock = one inference at a time per process; fine for a district
# reporting load, use a worker pool if submissions ever queue up behind it.
_lock = threading.Lock()


def _load(path):
    global _classifier
    if _classifier is None:
        if not os.path.isfile(os.path.join(path, 'model.safetensors')):
            raise VisionError('Vision model is not installed (run scripts/download_vision_model.py)')
        try:
            _classifier = SiglipClassifier(path)
        except Exception as e:  # ImportError (torch/transformers missing), corrupt files, ...
            raise VisionError(f'Vision model could not be loaded ({type(e).__name__})') from e
    return _classifier


def classify(image_bytes):
    """Classify one image given as bytes. Returns VisionResult; raises VisionError."""
    try:
        with Image.open(io.BytesIO(image_bytes)) as image:
            image = image.convert('RGB')
    except Exception as e:
        raise VisionError('Image could not be decoded') from e

    config = current_app.config
    with _lock:
        classifier = _load(config['VISION_MODEL_PATH'])
        try:
            scores = classifier.scores(image)
        except Exception as e:
            raise VisionError(f'Vision inference failed ({type(e).__name__})') from e

    best = max(HAZARD_LABELS, key=lambda label: scores[label])
    confidence = round(float(scores[best]), 4)
    label = best if confidence >= config['VISION_CONFIDENCE_THRESHOLD'] else UNKNOWN
    return VisionResult(label, confidence, config['VISION_MODEL_NAME'], config['VISION_MODEL_REVISION'][:12])
