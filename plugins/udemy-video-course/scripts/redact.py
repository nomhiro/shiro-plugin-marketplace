# -*- coding: utf-8 -*-
"""撮ったフレームに「塗りつぶし」と「強調」を入れる（公開前の必須工程）。

**塗りつぶし（黒ベタ）** — 個人情報と無関係な情報を消す。
  ぼかしは使わない。ぼかしは条件次第で復元されうるし、「隠したつもり」が残る。
  黒ベタなら不可逆で、視聴者にも「伏せてある」と伝わる。
  典型的な対象: 氏名・メールアドレス・テナント/サブスクリプション/リソースのID・
  他プロジェクトや他リソースの名前・コストの実額。

**強調（周囲を暗くして枠を描く）** — 1枚のスクリーンショットから複数の区間を作る。
  管理画面は1画面の情報量が多く、ナレーションだけでは視線が定まらない。
  同じ画像に別の枠を描いて並べると、「いまここを見る」が伝わる。

座標は `--probe` で先に確かめる（拡大して切り出すだけ。当てずっぽうで塗らない）:

    python redact.py --probe shot.jpg --box 900,240,1120,320 --out probe.png

本番はレシピ（JSON）で一括処理する:

    [
      {"src": "p01.jpg", "out": "f01.jpg", "blackout": [[748, 80, 882, 120]]},
      {"src": "p01.jpg", "out": "f02.jpg", "blackout": [[748, 80, 882, 120]],
       "highlight": [1163, 6, 1425, 40]},
      {"src": "p05.jpg", "out": "f07.jpg", "blackout": [[938, 264, 1062, 300]]}
    ]

    python redact.py recipe.json --src-dir ./raw --out-dir ./frames
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from PIL import Image, ImageDraw

ACCENT = (255, 176, 0)
INK = (10, 10, 10)


def blackout(im: Image.Image, boxes) -> Image.Image:
    d = ImageDraw.Draw(im)
    for b in boxes:
        d.rectangle(tuple(b), fill=INK)
    return im


def highlight(im: Image.Image, box, dim: float = 0.55, width: int = 4) -> Image.Image:
    """box の外側を暗くし、box に枠を描く。"""
    base = im.convert("RGB")
    out = Image.blend(base, Image.new("RGB", base.size, (0, 0, 0)), dim)
    out.paste(base.crop(tuple(box)), (box[0], box[1]))
    ImageDraw.Draw(out).rectangle(tuple(box), outline=ACCENT, width=width)
    return out


def probe(src: Path, box, out: Path, zoom: int = 3) -> None:
    im = Image.open(src).convert("RGB").crop(tuple(box))
    im.resize((im.width * zoom, im.height * zoom), Image.LANCZOS).save(out)
    print(f"切り出し {box} を {zoom}倍で保存: {out}")
    print("  → 画像を開いて、消したい文字が枠に収まっているか確かめる")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("recipe", type=Path, nargs="?")
    ap.add_argument("--src-dir", type=Path, default=Path("."))
    ap.add_argument("--out-dir", type=Path, default=Path("./frames"))
    ap.add_argument("--dim", type=float, default=0.55)
    ap.add_argument("--quality", type=int, default=92)
    ap.add_argument("--probe", type=Path, help="座標確認モード：この画像を切り出す")
    ap.add_argument("--box", help="x0,y0,x1,y1")
    ap.add_argument("--zoom", type=int, default=3)
    ap.add_argument("--out", type=Path, default=Path("probe.png"))
    a = ap.parse_args()

    if a.probe:
        if not a.box:
            raise SystemExit("--probe には --box x0,y0,x1,y1 が要ります")
        probe(a.probe, [int(x) for x in a.box.split(",")], a.out, a.zoom)
        return 0

    if not a.recipe:
        raise SystemExit("レシピ(JSON) か --probe のどちらかを指定してください")

    a.out_dir.mkdir(parents=True, exist_ok=True)
    steps = json.loads(a.recipe.read_text(encoding="utf-8"))
    for s in steps:
        im = Image.open(a.src_dir / s["src"]).convert("RGB")
        if s.get("blackout"):
            im = blackout(im, s["blackout"])
        if s.get("highlight"):
            im = highlight(im, s["highlight"], s.get("dim", a.dim))
        out = a.out_dir / s["out"]
        if out.suffix.lower() in (".jpg", ".jpeg"):
            im.save(out, "JPEG", quality=a.quality)
        else:
            im.save(out)
        marks = []
        if s.get("blackout"):
            marks.append(f"塗り{len(s['blackout'])}")
        if s.get("highlight"):
            marks.append("強調")
        print(f"  {s['out']:12s} {im.size}  {'/'.join(marks) or '加工なし'}")
    print(f"\n{len(steps)} 枚を {a.out_dir} に書き出しました。")
    print("  ※ 書き出した全フレームを目視し、黒ベタから文字がはみ出していないか確かめる")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
