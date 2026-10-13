"""Export of the article as a standalone page: ``python -m clanek OUT_DIR``.

Writes OUT_DIR/index.html and OUT_DIR/img/*, e.g. for sending the article to a journal."""
import shutil
import sys
from pathlib import Path

from . import IMG, images, render

out = Path(sys.argv[1] if len(sys.argv) > 1 else "clanek-export")
(out / "img").mkdir(parents=True, exist_ok=True)
(out / "index.html").write_text(render(), encoding="utf-8")
for name in images():
    shutil.copy2(IMG / name, out / "img" / name)
print(out / "index.html")
