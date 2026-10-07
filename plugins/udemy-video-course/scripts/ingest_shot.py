#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""撮ったスクリーンショットを、寸法を確かめてから素材（raw/S###.jpg）に取り込む。

ブラウザの拡張で撮ると、表示領域が途中で変わる・描画が左上だけになる・縮んだまま戻らない、
が起きる（実測）。**寸法が想定と違う枚は記録しない**（拡大縮小で合わせない。文字の大きさが
区間ごとに変わって見える）。合わない枚が出たら、窓の大きさを直して撮り直す。

取り込み:
    python ingest_shot.py add --work <作業ディレクトリ> --from <スクショのファイルかフォルダ> \\
        --expect 1350x703 <区間> <メモ…>
  --from にフォルダを渡すと、その中のいちばん新しい画像を取る。フォルダは環境変数 SHOT_DIR でも渡せる。
  寸法が --expect より最大 --crop-tolerance px 大きいだけなら、右と下を切って合わせる（縮めはしない）。
  記録は <作業ディレクトリ>/shots.tsv（ID・区間・時刻・元のファイル名・メモ）。

窓の大きさの決め方（表示倍率 DPR が 1 でない画面では、窓の大きさ ≠ 表示領域）:
  窓の大きさを2通り試し、それぞれの表示領域（JavaScript の innerWidth / innerHeight）を測る。
  表示領域は窓の大きさに対しほぼ一次式なので、2点から目標の表示領域になる窓の大きさを出せる。
    python ingest_shot.py fit-window --sample 1700x1063=1350x703 --sample 1350x703=1070x415 --target 1350x703
  出した値で窓を合わせたら、**もう一度表示領域を測って**目標どおりかを確かめる（DPR は機械ごとに違う）。

終了コード: 0＝取り込んだ／1＝寸法が合わず記録しなかった／2＝画像が見つからない。
"""
from __future__ import annotations

import argparse
import datetime as dt
import os
import re
import sys
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

IMAGE_EXT = (".jpg", ".jpeg", ".png")


def parse_wh(s: str) -> tuple[int, int]:
    m = re.fullmatch(r"\s*(\d+)\s*[xX×]\s*(\d+)\s*", s)
    if not m:
        raise argparse.ArgumentTypeError(f"WxH の形で書いてください: {s}")
    return int(m.group(1)), int(m.group(2))


def fit_crop(actual: tuple[int, int], expect: tuple[int, int], tol: int) -> tuple[int, int, int, int] | None:
    """寸法が expect と同じなら全体、少しだけ大きい（tol 以内）なら左上から切る箱、それ以外は None。"""
    (aw, ah), (ew, eh) = actual, expect
    if 0 <= aw - ew <= tol and 0 <= ah - eh <= tol:
        return (0, 0, ew, eh)
    return None


def solve_window(samples: list[tuple[tuple[int, int], tuple[int, int]]],
                 target: tuple[int, int]) -> tuple[int, int]:
    """[(窓の大きさ, 表示領域)] の2点から、表示領域が target になる窓の大きさを一次式で出す。"""
    if len(samples) < 2:
        raise ValueError("2点以上を測ってください")
    (w1, h1), (vw1, vh1) = samples[0]
    (w2, h2), (vw2, vh2) = samples[1]
    if w1 == w2 or h1 == h2:
        raise ValueError("窓の大きさを縦横とも変えた2点を使ってください")
    aw, ah = (vw2 - vw1) / (w2 - w1), (vh2 - vh1) / (h2 - h1)
    bw, bh = vw1 - aw * w1, vh1 - ah * h1
    return round((target[0] - bw) / aw), round((target[1] - bh) / ah)


def newest_image(d: Path) -> Path | None:
    imgs = [p for p in d.iterdir() if p.suffix.lower() in IMAGE_EXT]
    return max(imgs, key=lambda p: p.stat().st_mtime) if imgs else None


def next_id(raw: Path) -> str:
    nums = [int(m.group(1)) for p in raw.glob("S*.jpg") if (m := re.fullmatch(r"S(\d+)\.jpg", p.name))]
    return f"S{(max(nums) if nums else 0) + 1:03d}"


def cmd_add(a) -> int:
    from PIL import Image
    src = Path(a.src or os.environ.get("SHOT_DIR") or "")
    if not str(src):
        print("--from か SHOT_DIR でスクリーンショットの場所を指定してください")
        return 2
    if src.is_dir():
        src = newest_image(src)
    if not src or not src.exists():
        print(f"画像が見つかりません: {a.src}")
        return 2
    raw = a.work / "raw"
    raw.mkdir(parents=True, exist_ok=True)
    im = Image.open(src).convert("RGB")
    box = fit_crop(im.size, a.expect, a.crop_tolerance)
    note = " ".join(a.note)
    if box is None:
        print(f"!! 寸法が {im.width}x{im.height}（想定 {a.expect[0]}x{a.expect[1]}）：記録しなかった（{note}）")
        print("   窓の大きさを直して撮り直す（fit-window を参照）。描画が左上だけになったらタブを作り直す。")
        return 1
    sid = next_id(raw)
    im.crop(box).save(raw / f"{sid}.jpg", quality=95)
    with open(a.work / "shots.tsv", "a", encoding="utf-8") as f:
        f.write(f"{sid}\t{a.segment}\t{dt.datetime.now():%H:%M:%S}\t{src.name}\t{note}\n")
    print(f"{sid} ({a.segment}) {box[2]}x{box[3]} {note}  <- {src.name}")
    return 0


def cmd_fit(a) -> int:
    samples = [tuple(parse_wh(x) for x in s.split("=", 1)) for s in a.sample]
    w, h = solve_window(samples, a.target)
    print(f"窓の大きさ {w}x{h} で表示領域が {a.target[0]}x{a.target[1]} になる見込み。合わせたら測り直す。")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    pa = sub.add_parser("add", help="いちばん新しいスクリーンショットを寸法を確かめて取り込む")
    pa.add_argument("--work", type=Path, default=Path.cwd())
    pa.add_argument("--from", dest="src", default=None, help="画像ファイルかフォルダ（既定は環境変数 SHOT_DIR）")
    pa.add_argument("--expect", type=parse_wh, required=True, help="想定の寸法 WxH")
    pa.add_argument("--crop-tolerance", type=int, default=2, help="これ以内に大きいだけなら切って合わせる（px）")
    pa.add_argument("segment", help="区間（台本の区間名や番号）")
    pa.add_argument("note", nargs="*", help="メモ")
    pa.set_defaults(func=cmd_add)
    pf = sub.add_parser("fit-window", help="2点の実測から、目標の表示領域になる窓の大きさを出す")
    pf.add_argument("--sample", action="append", required=True, help="窓WxH=表示領域WxH（2つ以上）")
    pf.add_argument("--target", type=parse_wh, required=True)
    pf.set_defaults(func=cmd_fit)
    a = ap.parse_args(argv)
    return a.func(a)


if __name__ == "__main__":
    raise SystemExit(main())
