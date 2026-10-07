#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""撮ったフレーム（raw/）の映り込みを、OCR で見つけて黒ベタで塗る。

座標を手で決めて塗るやり方は、枚数が増えると必ず漏れる（実測：手で塗った回の点検で、
氏名・サブスクリプション ID・他プロジェクトの名前の塗り残しが重大判定になった）。
ここでは**規則で塗り、塗った後にもう一度 OCR して0件を確かめる**（leak_check_ocr.py）。
目視は最後の確認として、コンタクトシートで全数を見る（cue_stills.py --frame-dir masked）。

規則は**講座側の設定ファイル**（例 `leak_rules.yaml`）に置き、**git の管理外にする**
（氏名やアカウント名そのものを書くファイルなので、リポジトリにもこのプラグインにも入れない）。
雛形は templates/leak_rules.example.yaml。塗る規則と点検の規則は同じファイルから読む。

探し方（どれも規則ファイルで指定する）:
  1. words        OCR の語が正規表現に当たったら、その語の箱を pad だけ広げて塗る
  2. template     words のうち template: true の語は、見つかった切り抜きで全枚数を照合し、
                  OCR が読み落とした行（崩れた文字・暗い背景）も塗る
  3. label_value  「サブスクリプション ID」のようなラベルの右にある値を、width だけ塗る
                  （管理画面が自分でぼかして見せる ID も、ぼかしに頼らず塗る）
  4. fixed_boxes  位置が固定の表示（右上のアカウントなど）を箱で塗る。except で端末の枚などを外す
  5. guid         GUID の部分だけを塗る（keep に書いた GUID は語りで触れるので残す）
  6. price        金額（$1.23・USD）を含む語を塗る（講座で金額を断定しないため）

    python ocr_mask.py --work <作業ディレクトリ> --rules <講座>/leak_rules.yaml
    python ocr_mask.py --work . --rules ../leak_rules.yaml --reocr     # OCR をやり直す

出力（作業ディレクトリ）:
  ocr.json    OCR の結果のキャッシュ（後から足した枚だけ読む）
  masks.json  {画像名: [[x0,y0,x1,y1], ...]}。render_frames.py が recipe の blackout に足して塗る
  masked/     塗っただけの画像（強調なし）。leak_check_ocr.py と目視の検収に使う
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

FULLGUID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", re.I)
GUID = re.compile(r"[0-9a-f]{3,8}-[0-9a-f]{4}-[0-9a-f]{4}-", re.I)
PRICE = re.compile(r"\$\s?\d|USD|￥\s?\d|¥\s?\d")
IMAGE_GLOB = ("*.jpg", "*.jpeg", "*.png")


# ---------------------------------------------------------------- 規則
def load_rules(path: Path) -> dict:
    text = path.read_text(encoding="utf-8")
    if path.suffix.lower() == ".json":
        rules = json.loads(text)
    else:
        import yaml
        rules = yaml.safe_load(text) or {}
    return compile_rules(rules)


def compile_rules(rules: dict) -> dict:
    """設定ファイルの dict を、照合に使える形（正規表現をコンパイル済み）にする。"""
    words = [{"re": re.compile(w["pattern"], re.I), "pad": list(w.get("pad", [-4, -3, 4, 3])),
              "template": bool(w.get("template"))} for w in rules.get("words") or []]
    labels = [{"re": re.compile(l["pattern"]), "width": int(l.get("width", 260))}
              for l in rules.get("label_value") or []]
    fixed = [{"box": list(f["box"]), "except": re.compile(f["except"]) if f.get("except") else None}
             for f in rules.get("fixed_boxes") or []]
    guid = rules.get("guid") or {}
    return {
        "words": words, "label_value": labels, "fixed_boxes": fixed,
        "guid": bool(guid.get("enabled", False)), "guid_keep": tuple(guid.get("keep") or ()),
        "price": bool(rules.get("price", False)),
        "check_extra": [re.compile(x, re.I) for x in (rules.get("check") or {}).get("extra") or []],
        "fill": tuple(rules.get("fill") or (10, 10, 10)),
        "template_threshold": float(rules.get("template_threshold", 0.88)),
    }


def _span_x(x0: int, x1: int, text: str, start: int, end: int) -> tuple[float, float]:
    """語の箱の中で、文字位置 start〜end が占める x の範囲（文字幅を均等とみなす）。"""
    n = max(1, len(text))
    return x0 + (x1 - x0) * start / n, x0 + (x1 - x0) * end / n


def boxes_for(name: str, words: list, rules: dict) -> list[list[int]]:
    """1枚分の OCR 結果 [([x0,y0,x1,y1], 文字列), ...] から、塗る箱を出す（純粋な関数）。"""
    out: list[list[int]] = []
    for f in rules["fixed_boxes"]:
        if f["except"] is None or not f["except"].search(name):
            out.append(list(f["box"]))
    for (x0, y0, x1, y1), t in words:
        for w in rules["words"]:
            if w["re"].search(t):
                l, u, r, d = w["pad"]
                out.append([x0 + l, y0 + u, x1 + r, y1 + d])
        for lv in rules["label_value"]:
            if lv["re"].search(t):
                out.append([x1 + 4, y0 - 4, x1 + 4 + lv["width"], y1 + 4])
        if rules["price"] and PRICE.search(t):
            out.append([x0 - 4, y0 - 3, x1 + 4, y1 + 3])
        if rules["guid"]:
            m = GUID.search(t)
            if m and not any(k in t for k in rules["guid_keep"]):
                full = FULLGUID.search(t, m.start())
                end = full.end() if full and full.start() == m.start() else len(t)
                xs, xe = _span_x(x0, x1, t, m.start(), end)
                out.append([int(xs) - 8, y0 - 3, int(xe) + 6, y1 + 3])
    return out


def check_patterns(rules: dict) -> list[re.Pattern]:
    """塗った後の点検で「1件も読めてはいけない」正規表現の一覧（塗る規則と同じファイルから作る）。"""
    pats = [w["re"] for w in rules["words"]] + list(rules["check_extra"])
    if rules["guid"]:
        pats.append(GUID)
    if rules["price"]:
        pats.append(PRICE)
    return pats


def leak_hits(name: str, words: list, rules: dict) -> list[str]:
    """点検：1枚分の OCR 結果のうち、規則に当たる語（keep に書いた GUID は除く）。"""
    hits = []
    for _box, t in words:
        if rules["guid"] and GUID.search(t) and any(k in t for k in rules["guid_keep"]):
            continue
        if any(p.search(t) for p in check_patterns(rules)):
            hits.append(t)
    return hits


# ---------------------------------------------------------------- OCR（重い依存は呼ぶときに読む）
def _ocr_engine():
    from rapidocr_onnxruntime import RapidOCR
    return RapidOCR()


def ocr_image(engine, path: Path) -> list:
    res, _ = engine(str(path))
    return [([int(min(q[0] for q in b)), int(min(q[1] for q in b)),
              int(max(q[0] for q in b)), int(max(q[1] for q in b))], t)
            for b, t, _s in (res or [])]


def list_images(d: Path) -> list[Path]:
    return sorted({p for g in IMAGE_GLOB for p in d.glob(g)})


def ocr_dir(src: Path, cache: Path | None, reocr: bool = False) -> dict:
    data = {}
    if cache and cache.exists() and not reocr:
        data = json.loads(cache.read_text(encoding="utf-8"))
    todo = [p for p in list_images(src) if p.name not in data]
    if todo:
        eng = _ocr_engine()
        for p in todo:
            data[p.name] = ocr_image(eng, p)
        if cache:
            cache.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    return data


def template_pass(src: Path, ocr: dict, masks: dict, rules: dict) -> int:
    """template: true の語の切り抜きで全枚数を照合し、OCR が読み落とした箇所も塗る。"""
    if not any(w["template"] for w in rules["words"]):
        return 0
    import cv2
    import numpy as np
    from PIL import Image
    tpls = []
    for name, words in ocr.items():
        im = np.array(Image.open(src / name).convert("L"))
        for (x0, y0, x1, y1), t in words:
            for w in rules["words"]:
                if w["template"] and w["re"].search(t) and len(tpls) < 40 and x1 > x0 and y1 > y0:
                    tpls.append((im[y0:y1, x0:x1].copy(), w["pad"]))
    added = 0
    for name in ocr:
        im = np.array(Image.open(src / name).convert("L"))
        for tp, (l, u, r, d) in tpls:
            if tp.shape[0] > im.shape[0] or tp.shape[1] > im.shape[1]:
                continue
            res = cv2.matchTemplate(im, tp, cv2.TM_CCOEFF_NORMED)
            for y, x in zip(*np.where(res >= rules["template_threshold"])):
                b = [int(x) + l, int(y) + u, int(x) + tp.shape[1] + r, int(y) + tp.shape[0] + d]
                if not any(abs(b[0] - c[0]) < 20 and abs(b[1] - c[1]) < 8 for c in masks[name]):
                    masks[name].append(b)
                    added += 1
    return added


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--work", type=Path, default=Path.cwd(), help="作業ディレクトリ（raw/ がある所）")
    ap.add_argument("--rules", type=Path, required=True, help="講座側の規則ファイル（YAML か JSON）")
    ap.add_argument("--src", default="raw", help="塗る元の画像フォルダ（作業ディレクトリからの相対）")
    ap.add_argument("--reocr", action="store_true", help="OCR のキャッシュを使わずに読み直す")
    a = ap.parse_args(argv)
    from PIL import Image, ImageDraw
    w = a.work.resolve()
    src = w / a.src
    rules = load_rules(a.rules)
    ocr = ocr_dir(src, w / "ocr.json", a.reocr)
    masks = {name: boxes_for(name, words, rules) for name, words in ocr.items()}
    print("テンプレート照合で追加:", template_pass(src, ocr, masks, rules))
    out = w / "masked"
    out.mkdir(exist_ok=True)
    for name, bx in masks.items():
        im = Image.open(src / name).convert("RGB")
        d = ImageDraw.Draw(im)
        for b in bx:
            d.rectangle([max(0, b[0]), max(0, b[1]), min(im.width - 1, b[2]), min(im.height - 1, b[3])],
                        fill=rules["fill"])
        im.save(out / name, quality=92)
    (w / "masks.json").write_text(json.dumps(masks, indent=0), encoding="utf-8")
    print(f"塗った枚数: {len(masks)} / 箱の合計: {sum(len(v) for v in masks.values())}")
    print("次に: python leak_check_ocr.py --work . --rules <同じ規則ファイル>（0件を確かめる）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
