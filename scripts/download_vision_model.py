"""Download the M06 vision model into instance/models/ (gitignored). One-time, needs internet.

    pip install -r requirements-vision.txt
    python scripts/download_vision_model.py

Model: google/siglip-base-patch16-224 (Apache-2.0), pinned to a fixed revision.
The app itself never downloads anything: it loads with local_files_only=True.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from huggingface_hub import snapshot_download  # noqa: E402

from app.config import Config  # noqa: E402

FILES = ['config.json', 'model.safetensors', 'preprocessor_config.json', 'special_tokens_map.json',
         'spiece.model', 'tokenizer_config.json']

if __name__ == '__main__':
    path = snapshot_download(Config.VISION_MODEL_NAME, revision=Config.VISION_MODEL_REVISION,
                             local_dir=Config.VISION_MODEL_PATH, allow_patterns=FILES)
    print(f'Vision model ready at {path}')
