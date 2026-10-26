"""Export of the article as a standalone page: ``python -m clanek OUT_DIR [--lang cs|en|de]``.

Writes OUT_DIR/index.html and OUT_DIR/img/*, e.g. for sending the article to a journal."""
import argparse
import shutil
from pathlib import Path

from . import LANGS, images, img_dir, render

ap = argparse.ArgumentParser(prog="python -m clanek")
ap.add_argument("out", nargs="?", default="clanek-export")
ap.add_argument("--lang", choices=LANGS, default="cs")
args = ap.parse_args()
out = Path(args.out)
(out / "img").mkdir(parents=True, exist_ok=True)
(out / "index.html").write_text(render(args.lang, links=False), encoding="utf-8")
for name in images(args.lang):
    shutil.copy2(img_dir(args.lang) / name, out / "img" / name)
print(out / "index.html")
