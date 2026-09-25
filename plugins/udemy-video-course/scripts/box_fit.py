# -*- coding: utf-8 -*-
"""強調枠を「文字から離して」置き直し、すき間まで検査する（v2）。

旧 check_overlap.py は枠線が塗る4px帯の真下しか見ておらず、文字の1px外側に
接した枠を合格にしていた（完成動画ではディセンダーや行頭が枠線に食われる）。

方針:
  1. make_recipe.py の枠（意図した範囲）と縦に重なる文字の行を対象とし、その外接矩形を取る。
  2. 各辺について、対象の文字と「外側で最も近い別の文字」のあいだの空き帯を測り、
     枠線(4px)を対象から GOAL px 離して置く。空きが足りなければ空き帯の中央に置く。
  3. 検査: 枠線の帯を内外へ CLEAR px 広げた範囲に文字インクが1画素でもあれば NG。
     インクの閾値は背景+35（旧版の55より低く、アンチエイリアスの縁も拾う）。
     文字ではないもの（カーソル、インデントガイド、パネルの境界線）は除外する：
     縦に RUN_V px 以上続くインク列、横に RUN_H px 以上続くインク行。

なぜ要るか: 強調枠を目分量や OCR の外接矩形で置くと、枠線が文字に接する・かぶる。
数値レビューでは気づけず、完成動画で「枠で文字が読めない」と指摘される（実測：10本で56件）。
枠線と文字のすき間 CLEAR(3px) を機械で保証する。

使い方（作業ディレクトリ = recipe.json と raw/ がある場所）:
    python box_fit.py --work <作業ディレクトリ>            # recipe.json を書き換え、結果を表示
    python box_fit.py --work <作業ディレクトリ> --check    # 検査だけ

recipe.json の各要素: {"src", "out", "highlight": [x0,y0,x1,y1], "blackout"?: [[...]], "width"?}
  - 初回は highlight を「意図の範囲」とみなし "intent" に控えてから置き直す（再実行しても意図は保たれる）。
  - 4px で空きが足りなければ 3px → 2px に細くする（行間の詰まった一覧・エディター向け）。
  - 自動配置が誤認する区間（カーソル、スクロールバー、エディターのヒント記号）は
    作業ディレクトリの box_manual.json に {"r15.jpg": [[x0,y0,x1,y1], 4], ...} で手置きする。
    手置きも check() で検査される。拡大図で目視してから置くこと。
  - コードを映す区間は、撮影時にエディターの行間（editor.lineHeight）を 2.0 にしておくと
    枠線の入る空きができ、自動配置で通りやすい。
"""
import argparse
import json
import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

WORK = Path.cwd()
RAW = WORK / "raw"
STROKE = 4
T = 35
GOAL = 6
CLEAR = 3
RUN_V = 20      # 文字の縦画はこれより短い（行の高さ未満）
RUN_H = 200     # 表の罫線 "-----" は文字として扱いたいので、長い横線だけ除外
NOISE = 2       # 1行(1列)にインクがこれ未満なら雑音（細いカーソルの切れ端など）として無視
ALLOW = 2       # 検査で許す孤立画素の数


def _max_run(a, axis):
    """bool 配列の axis 方向の最長連続長"""
    a = a if axis == 0 else a.T
    best = np.zeros(a.shape[1], int)
    cur = np.zeros(a.shape[1], int)
    for row in a:
        cur = np.where(row, cur + 1, 0)
        best = np.maximum(best, cur)
    return best


def ink_mask(src, blackout=None):
    im = Image.open(RAW / src).convert("RGB")
    if blackout:
        d = ImageDraw.Draw(im)
        for b in blackout:
            d.rectangle(tuple(b), fill=(10, 10, 10))
    L = np.asarray(im.convert("L"), dtype=np.int16)
    H, W = L.shape
    # 局所背景: 32px ブロックごとの25パーセンタイル
    bg = np.zeros_like(L)
    B = 32
    for y in range(0, H, B):
        for x in range(0, W, B):
            blk = L[max(0, y - B):y + 2 * B, max(0, x - B):x + 2 * B]
            bg[y:y + B, x:x + B] = np.percentile(blk, 25)
    ink = L > bg + T
    # 縦に長く続く列（カーソル・インデントガイド・境界線）を除外
    out = ink.copy()
    for x in range(W):
        col = ink[:, x]
        if not col.any():
            continue
        run = 0
        for y in range(H + 1):
            v = col[y] if y < H else False
            if v:
                run += 1
            else:
                if run >= RUN_V:
                    out[y - run:y, x] = False
                run = 0
    for y in range(H):
        row = ink[y]
        if not row.any():
            continue
        run = 0
        for x in range(W + 1):
            v = row[x] if x < W else False
            if v:
                run += 1
            else:
                if run >= RUN_H:
                    out[y, x - run:x] = False
                run = 0
    return out


def place_low(target, other, goal, STROKE=STROKE):
    CLEAR = 3 if STROKE >= 3 else 2
    """上辺・左辺。target=対象インクの最小座標, other=外側の最も近いインク座標。
    枠線の先頭座標と、対象とのすき間を返す。"""
    ideal = target - goal - STROKE
    if other is None or ideal - other - 1 >= CLEAR:
        return ideal, goal
    free = target - other - 1
    d_t = (free - STROKE + 1) // 2
    return target - d_t - STROKE, d_t


def place_high(target, other, goal, STROKE=STROKE):
    CLEAR = 3 if STROKE >= 3 else 2
    """下辺・右辺。枠線の先頭座標と、対象とのすき間を返す。"""
    ideal = target + goal + 1
    if other is None or other - (ideal + STROKE - 1) - 1 >= CLEAR:
        return ideal, goal
    free = other - target - 1
    d_t = (free - STROKE + 1) // 2
    return target + d_t + 1, d_t


def fit(ink, box, STROKE=STROKE):
    H, W = ink.shape
    x0, y0, x1, y1 = [int(v) for v in box]
    # 1) 意図の枠と縦に重なる行（インクの連続区間）を対象にする
    rows = ink[:, x0:x1 + 1].sum(axis=1) >= NOISE
    runs, a = [], None
    for y in range(H + 1):
        v = rows[y] if y < H else False
        if v and a is None:
            a = y
        elif not v and a is not None:
            runs.append((a, y - 1))
            a = None
    tgt = [r for r in runs if min(r[1], y1) - max(r[0], y0) + 1 >= max(3, (r[1] - r[0] + 1) * 0.5)]
    if not tgt:
        return list(box), {}
    iy0, iy1 = tgt[0][0], tgt[-1][1]
    cols = np.where(ink[iy0:iy1 + 1, x0:x1 + 1].sum(axis=0) >= NOISE)[0]
    if not len(cols):
        return list(box), {}
    ix0, ix1 = x0 + cols[0], x0 + cols[-1]
    # 枠の縁で切れている字（行頭の○など）は、続いている限り対象に含める
    colany = ink[iy0:iy1 + 1, :].sum(axis=0) >= NOISE
    while ix0 - 1 >= 0 and colany[max(0, ix0 - 6):ix0].any():
        ix0 = max(0, ix0 - 6) + int(np.where(colany[max(0, ix0 - 6):ix0])[0][0])
    while ix1 + 1 < W and colany[ix1 + 1:ix1 + 7].any():
        ix1 = ix1 + 1 + int(np.where(colany[ix1 + 1:ix1 + 7])[0][-1])
    # 2) 上下
    sx0, sx1 = max(0, ix0 - 16), min(W - 1, ix1 + 16)
    band = ink[:, sx0:sx1 + 1].sum(axis=1) >= NOISE
    ab = np.where(band[max(0, iy0 - 40):iy0])[0]
    o_top = max(0, iy0 - 40) + ab[-1] if len(ab) else None
    be = np.where(band[iy1 + 1:min(H, iy1 + 41)])[0]
    o_bot = iy1 + 1 + be[0] if len(be) else H
    top, gt = place_low(iy0, o_top, GOAL, STROKE)
    bot, gb = place_high(iy1, o_bot, GOAL, STROKE)
    top, bot = max(0, top), min(H - STROKE, bot)
    # 3) 左右（枠の高さ全体で見る）
    colband = ink[top:bot + STROKE, :].sum(axis=0) >= NOISE
    lb = np.where(colband[max(0, ix0 - 40):ix0])[0]
    o_l = max(0, ix0 - 40) + lb[-1] if len(lb) else None
    rb = np.where(colband[ix1 + 1:min(W, ix1 + 41)])[0]
    o_r = ix1 + 1 + rb[0] if len(rb) else W
    left, gl = place_low(ix0, o_l, GOAL + 2, STROKE)
    right, gr = place_high(ix1, o_r, GOAL + 2, STROKE)
    left, right = max(0, left), min(W - STROKE, right)
    new = [int(left), int(top), int(right + STROKE - 1), int(bot + STROKE - 1)]
    return new, {"t": gt, "b": gb, "l": gl, "r": gr}


def check(ink, box, STROKE=STROKE):
    """枠線の帯を内外へ CLEAR 広げた範囲のインク。2px の細線だけは CLEAR を2にする
    （行間の詰まった一覧で、線を行間の真ん中に置けば上下2pxずつ空く）。"""
    CLEAR = 3 if STROKE >= 3 else 2
    H, W = ink.shape
    x0, y0, x1, y1 = [int(v) for v in box]
    def c(a0, a1, b0, b1, axis):
        blk = ink[max(0, b0):min(H, b1 + 1), max(0, a0):min(W, a1 + 1)]
        per = blk.sum(axis=axis)          # 帯に沿った1行(1列)ごとのインク数
        return int(per[per >= NOISE].sum())
    hits = {
        "top": c(x0, x1, y0 - CLEAR, y0 + STROKE - 1 + CLEAR, 1),
        "bottom": c(x0, x1, y1 - STROKE + 1 - CLEAR, y1 + CLEAR, 1),
        "left": c(x0 - CLEAR, x0 + STROKE - 1 + CLEAR, y0, y1, 0),
        "right": c(x1 - STROKE + 1 - CLEAR, x1 + CLEAR, y0, y1, 0),
    }
    return {k: v for k, v in hits.items() if v > ALLOW}


MANUAL: dict = {}


def main():
    global WORK, RAW, MANUAL
    ap = argparse.ArgumentParser()
    ap.add_argument("--work", type=Path, default=Path.cwd(), help="recipe.json と raw/ がある作業ディレクトリ")
    ap.add_argument("--check", action="store_true", help="置き直さず検査だけ")
    a = ap.parse_args()
    WORK, RAW = a.work.resolve(), a.work.resolve() / "raw"
    mf = WORK / "box_manual.json"
    MANUAL = {k: (v[0], v[1]) for k, v in json.loads(mf.read_text(encoding="utf-8")).items()} if mf.exists() else {}
    rp = WORK / "recipe.json"
    recipe = json.loads(rp.read_text(encoding="utf-8"))
    only_check = a.check
    bad = 0
    cache = {}
    for s in recipe:
        hl = s.get("highlight")
        if not hl:
            continue
        key = (s["src"], json.dumps(s.get("blackout")))
        if key not in cache:
            cache[key] = ink_mask(s["src"], s.get("blackout"))
        ink = cache[key]
        gap = {}
        w = s.get("width", STROKE)
        if not only_check and s["out"] in MANUAL:
            hl, w = MANUAL[s["out"]]
            s["highlight"], s["width"] = hl, w
        elif not only_check:
            orig = s.get("intent", hl)
            s["intent"] = orig
            # 4px で空きが足りなければ 3px → 2px に細くする（詰まった行間のエクスプローラー・メニュー・エディター向け）
            for w in (4, 3, 2):
                hl, gap = fit(ink, orig, w)
                if not check(ink, hl, w):
                    break
            s["highlight"] = hl
            s["width"] = w
        hits = check(ink, hl, w)
        bad += bool(hits)
        print(f"{'NG' if hits else 'ok'} {s['out']:<8} {s['src']:<12} w={w} box={hl} gap={ {k: int(v) for k, v in gap.items()} } hits={hits}")
    if not only_check:
        rp.write_text(json.dumps(recipe, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"\nNG: {bad} / {sum(1 for s in recipe if s.get('highlight'))}")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
