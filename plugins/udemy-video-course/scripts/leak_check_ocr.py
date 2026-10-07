#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""塗った後のフレームをもう一度 OCR し、規則に当たる語が**1件も読めない**ことを確かめる。

ocr_mask.py と**同じ規則ファイル**を読む（塗る規則と点検の規則がずれないように）。
点検の対象は、塗る規則の words・guid・price に、規則ファイルの check.extra を足したもの。

    python leak_check_ocr.py --work <作業ディレクトリ> --rules <講座>/leak_rules.yaml
    python leak_check_ocr.py --work . --rules ../leak_rules.yaml --dir frames   # 強調まで入れた絵も見る

終了コード: 0＝塗り残し 0 件／1＝塗り残しあり（枚と語を表示）／2＝画像が無い。
読めた語は報告に出すので、**ログを公開の場所に貼らない**（塗り残しの中身が残る）。
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

sys.path.insert(0, str(Path(__file__).resolve().parent))
from ocr_mask import _ocr_engine, leak_hits, list_images, load_rules, ocr_image  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--work", type=Path, default=Path.cwd())
    ap.add_argument("--rules", type=Path, required=True)
    ap.add_argument("--dir", default="masked", help="点検する画像フォルダ（既定 masked/。frames/ も可）")
    a = ap.parse_args(argv)
    rules = load_rules(a.rules)
    imgs = list_images(a.work.resolve() / a.dir)
    if not imgs:
        print(f"画像がありません: {a.work / a.dir}")
        return 2
    eng = _ocr_engine()
    hits = 0
    for p in imgs:
        for t in leak_hits(p.name, ocr_image(eng, p), rules):
            hits += 1
            print(f"  ✗ {p.name}: {t}")
    print(f"点検した枚数: {len(imgs)} / 塗り残し: {hits} 件")
    return 1 if hits else 0


if __name__ == "__main__":
    raise SystemExit(main())
