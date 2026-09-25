# -*- coding: utf-8 -*-
"""スライド区間と録画区間のナレーションを JSON に書き出す（build_rec.py の入力）。

- 録画区間のナレーションは make_recipe.py の R から取る（正本は R）。
- スライド区間は、旧版の slides.json（old/slides_v1.json）を元に作る。
  🔴 置換（PATCH）だけで済ませない。旧版の台本は**全文を読み直し**、新しい手順・事実と矛盾する文
  （料金・前提の数・エラーの例・用語）を洗い出してから直す。書き直した方が早ければ TEXT に全文を書く。

実行: python make_json.py <作業ディレクトリ>   → slides.json / frames.json
"""
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from make_recipe import R  # noqa: E402

W = Path(sys.argv[1]) if len(sys.argv) > 1 else HERE

SLIDES = json.loads((HERE / "old" / "slides_v1.json").read_text(encoding="utf-8"))

# 全文を書き直すスライド：スライド番号 → 本文
TEXT = {
    # 3: "前提です。…",
}

# 一部だけ直すスライド：(旧文, 新文)。旧文はちょうど1か所に当たること
PATCH = [
    # ("旧い文。", "新しい文。"),
]

for s in SLIDES:
    if s["n"] in TEXT:
        s["text"] = TEXT[s["n"]]
for old, new in PATCH:
    hit = [s for s in SLIDES if old in s["text"]]
    assert len(hit) == 1, old[:30]
    hit[0]["text"] = hit[0]["text"].replace(old, new)

RECS = [{"frame": f"r{i:02d}.jpg", "title": label, "text": text}
        for i, (_src, label, _hl, _bo, text) in enumerate(R, 1)]

(W / "slides.json").write_text(json.dumps(SLIDES, ensure_ascii=False, indent=1), encoding="utf-8")
(W / "frames.json").write_text(json.dumps(RECS, ensure_ascii=False, indent=1), encoding="utf-8")
print(f"wrote {len(SLIDES)} slides, {len(RECS)} recs")
