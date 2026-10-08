"""Publish a prepared NVDA dataset to private Vercel Blob.

Set BLOB_READ_WRITE_TOKEN securely, then run:
python scripts/publish_nvda.py data/nvda
This replaces the shared active NVDA manifest after uploading all chunks.
"""

import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from app.services.nvda_dataset import nvda_dataset

if __name__ == "__main__":
    if not os.environ.get("BLOB_READ_WRITE_TOKEN"):
        raise SystemExit("Set BLOB_READ_WRITE_TOKEN securely before publishing.")
    root = Path(sys.argv[1] if len(sys.argv) > 1 else "data/nvda")
    manifest = json.loads((root / "manifest.json").read_text())
    nvda_dataset.publish_prepared(root, manifest)
    print(f"Published NVDA day 0: {manifest['total_snapshots']} snapshots, {manifest['total_trades']} trades.")
