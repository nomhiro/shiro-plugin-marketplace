"""スナップショットの「インクが画面のどれだけを使っているか」を実測する。

## なぜ必要か

ユーザーの明示要件7:

> **アニメーションは画面全体を上手に使う。図は `layout.safe`（x 40→1880 / y 40→1040）
> まで広げる。中央に小さくまとめない。**

これは**目で見ても気づきにくい**（1枚ずつ見ると「まあ入っている」と思ってしまう）。
実際、2026-09-18 にユーザーから2回目の指摘を受けた
（1回目で要件7ができたのに、その後作った動画でも同じことが起きていた）。

**`lint` も `check` も構図の余白を見ない。** だからここで測る。

## 何を測るか

白（`#FFFFFF`）でない画素の外接矩形を求め、`layout.safe` に対する比で出す。

- **`fill`** … 外接矩形の面積 ÷ `layout.safe` の面積。**小さいほど画面を持て余している**
- **`余白`** … safe の各辺と外接矩形の間隔（px）。**一方向だけ大きく空いていたら偏り**
- **`density`** … インクの画素数 ÷ `layout.safe` の面積。
  **★ `fill` だけでは破れる。** 細い輪郭で画面を囲むと外接矩形は大きくなるが中身は空。
  実測（3-1-1 frame 1）: 中身のない巨大な四角が `fill` 95% を出したが、**絵は前より悪かった**。
  **`density` が 3% を切ったら「輪郭だけで面積を稼いでいないか」をコンタクトシートで確かめる。**

## 判定の目安（実測から）

| `fill` | 判定 |
|---|---|
| 60% 以上 | 画面を使えている |
| 40〜60% | 要検討（意味のある静けさなら可） |
| **40% 未満** | **持て余している。作り直す** |

**ただし機械の判定は「疑う根拠」であって結論ではない。**
落ちの前の一呼吸・締めの静止は**意図的に余白を残す**（`frame.md`）。
**数字が低い理由を説明できるかどうか**で判断する。

## 使い方

    npx hyperframes snapshot --at <各フレームの着地点>
    python check_coverage.py videos/<unit-slug>
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, OSError):
        pass

SAFE = (40, 40, 1880, 1040)  # frame.md の layout.safe
SAFE_AREA = (SAFE[2] - SAFE[0]) * (SAFE[3] - SAFE[1])
# 純白からこれ以上離れた画素を「インク」とみなす（JPEG/PNG の量子化を吸収）
INK_DELTA = 6
# ★ 2つ目の閾値。**読めるインクだけ**を数える（L < 230）。
#   ごく薄い面（frame-face の実効 α0.03 など）は輝度 248〜249 に来るので、
#   INK_DELTA=6（L<249）だけだと **0.34 の差で density が 40% と 1.6% に跳ぶ**
#   （sv-08 の実測 / 3-1-4 F8）。閾値を2つ出して崖を跨がせる。
READ_DELTA = 25
LOW_FILL = 0.40


def ink_box(path: Path):
    """外接矩形と、インクの画素数を返す。

    ★ 外接矩形だけでは足りない。**細い輪郭で画面を囲むだけで fill が跳ね上がる。**
    実測（2026-09-18・3-1-1 frame 1）: 中身のない巨大な四角が `fill` 95% を出したが、
    **絵としては前より悪くなっていた**（ユーザー要件の「効率よく使う」から外れる）。
    そこでインクの画素数も返し、`density` として併記する。
    """
    from PIL import Image

    im = Image.open(path).convert("L")
    w, h = im.size
    sx, sy = w / 1920.0, h / 1080.0
    px = im.load()
    x0, y0, x1, y1 = w, h, -1, -1
    ink = 0
    read = 0          # ★ 読めるインクだけ（L < 255 - READ_DELTA）
    for y in range(h):
        row_hit = False
        for x in range(w):
            v = px[x, y]
            if v < 255 - READ_DELTA:
                read += 1
            if v < 255 - INK_DELTA:
                ink += 1
                if x < x0: x0 = x
                if x > x1: x1 = x
                row_hit = True
        if row_hit:
            if y < y0: y0 = y
            if y > y1: y1 = y
    if x1 < 0:
        return None
    return (x0 / sx, y0 / sy, x1 / sx, y1 / sy, ink / (sx * sy), read / (sx * sy))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("units", nargs="+")
    ap.add_argument("--low", type=float, default=LOW_FILL)
    a = ap.parse_args()

    ng = 0
    for raw in a.units:
        unit = Path(raw)
        shots = sorted((unit / "snapshots").glob("frame-*.png"))
        if not shots:
            print("%s: snapshots/ に画像が無い（先に hyperframes snapshot）" % unit.name)
            continue
        print("\n=== %s ===" % unit.name)
        print("  %-26s %6s %8s %8s   %s"
              % ("snapshot", "fill", "density", "dens*", "safe との余白 左/上/右/下"))
        print("  %-26s %6s %8s %8s   %s"
              % ("", "", "(薄い面込)", "(読める)", ""))
        for s in shots:
            box = ink_box(s)
            if box is None:
                print("  %-26s %6s %8s %8s   （真っ白）" % (s.stem, "0%", "0%", "0%"))
                ng += 1
                continue
            x0, y0, x1, y1, ink_px, read_px = box
            fill = ((x1 - x0) * (y1 - y0)) / SAFE_AREA
            dens = ink_px / SAFE_AREA
            read = read_px / SAFE_AREA
            pads = (x0 - SAFE[0], y0 - SAFE[1], SAFE[2] - x1, SAFE[3] - y1)
            flag = ""
            if fill < a.low:
                flag = "  ★持て余し"; ng += 1
            elif read < 0.03:
                # ★ 判定は dens ではなく dens*（読めるインク）で行う。
                #   薄い面は fill を押し上げるが、読ませる情報を1つも足していない。
                flag = "  ★輪郭だけ？"
            if dens - read > 0.10:
                flag += "  ※薄い面が density を押し上げている"
            print("  %-26s %5.0f%% %7.1f%% %7.1f%%   %4.0f /%4.0f /%4.0f /%4.0f%s"
                  % (s.stem, 100 * fill, 100 * dens, 100 * read,
                     pads[0], pads[1], pads[2], pads[3], flag))

    if ng:
        print("\n★ fill が %.0f%% を切るフレームが %d 枚。" % (100 * a.low, ng))
        print("  ユーザー要件7「図は layout.safe まで広げる。中央に小さくまとめない」に照らして")
        print("  作り直すか、**なぜその余白が必要か**を説明できるか判断する。")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
