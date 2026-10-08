"""Make recompressed / resized / photographed copies of a folder of synthetic payment screenshots.

Run:  python -m tests.ingestion.make_degraded_screenshots data/synthetic/screenshots
Creates data/synthetic/degraded/<condition>/ with the same file names (stems). 'clean' = the original folder.
"""

import sys
from pathlib import Path

from PIL import Image

from tests.ingestion.degradation_eval import c_photographed, c_recompressed, c_resized

CONDITIONS = {"recompressed": c_recompressed, "resized": c_resized, "photographed": c_photographed}

if __name__ == "__main__":
    src = Path(sys.argv[1] if len(sys.argv) > 1 else "data/synthetic/screenshots")
    out_root = src.parent / "degraded"
    files = sorted(p for p in src.iterdir() if p.suffix.lower() in (".png", ".jpg", ".jpeg"))
    for name, fn in CONDITIONS.items():
        out = out_root / name
        out.mkdir(parents=True, exist_ok=True)
        for f in files:
            data, _ = fn(Image.open(f).convert("RGB"))
            ext = ".jpg" if data[:2] == b"\xff\xd8" else ".png"
            (out / (f.stem + ext)).write_bytes(data)
        print(f"{name}: {len(files)} files -> {out}")