# -*- coding: utf-8 -*-
"""recipe.json からフレームを描く（raw/ → frames/）。redact.py と同じ描き方で、
区間ごとの枠線の太さ（"width"。box_fit.py が 4/3/2 を選ぶ）と減光（"dim"）に対応する。

使い方: python render_frames.py --work <作業ディレクトリ>
"""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from PIL import Image  # noqa: E402
from redact import blackout, highlight  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--work", type=Path, default=Path.cwd())
    a = ap.parse_args()
    w = a.work.resolve()
    out = w / "frames"
    out.mkdir(exist_ok=True)
    for old in out.glob("r*.jpg"):
        old.unlink()
    for s in json.loads((w / "recipe.json").read_text(encoding="utf-8")):
        im = Image.open(w / "raw" / s["src"]).convert("RGB")
        if s.get("blackout"):
            im = blackout(im, s["blackout"])
        if s.get("highlight"):
            im = highlight(im, s["highlight"], s.get("dim", 0.55), s.get("width", 4))
        im.save(out / s["out"], quality=92)
    print(len(list(out.glob("r*.jpg"))), "frames")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
