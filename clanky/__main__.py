"""Export of an article as a standalone page (e.g. for sending it to a journal):

    python -m clanky do_posledni_kwh OUT_DIR [--lang cs|en|de]

Writes OUT_DIR/index.html and OUT_DIR/img/*."""
import argparse
import shutil
from pathlib import Path

from . import ARTICLES, LANGS, by_folder

ap = argparse.ArgumentParser(prog="python -m clanky")
ap.add_argument("article", choices=[a.folder for a in ARTICLES])
ap.add_argument("out", nargs="?", default="clanek-export")
ap.add_argument("--lang", choices=LANGS, default="cs")
args = ap.parse_args()
article = by_folder(args.article)
out = Path(args.out)
(out / "img").mkdir(parents=True, exist_ok=True)
(out / "index.html").write_text(article.render(args.lang, links=False), encoding="utf-8")
for name in article.images(args.lang):
    shutil.copy2(article.img_dir(args.lang) / name, out / "img" / name)
print(out / "index.html")
