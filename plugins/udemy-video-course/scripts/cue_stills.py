# -*- coding: utf-8 -*-
"""強調（クリック位置・注目枠）を当てた静止画を書き出し、コンタクトシートにまとめる。

**動画を組む前に、強調を1枚ずつ目で確かめるための道具**である。

なぜ要るか。強調の座標の誤りは、**数値を読んでも分からない**。
実測では4レクチャーで矩形の誤りが9件見つかり、そのうち座標のレビューで
気づけたものは0件だった。すべて「描いた絵を見て」初めて分かっている。
しかも欠陥は1本あたり1〜6件で30〜50枚に散らばるので、**抜き取りでは当たらない**。

一方、フレームを1枚ずつ読むと画像のコストが嵩む。そこで**4枚を1枚にまとめた
コンタクトシート**にする。画像の枚数が1/4になり、それでも矩形のずれは十分に見える。
**怪しい1枚だけ**、原寸の静止画（`--stills` で同時に書き出す）を開いて確かめる。

入力はレシピ（`redact.py` と同じ JSON）か、加工済みフレームのディレクトリ:

    [
      {"src": "p01.jpg", "out": "f01.jpg", "blackout": [[748, 80, 882, 120]]},
      {"src": "p01.jpg", "out": "f02.jpg", "highlight": [1163, 6, 1425, 40],
       "kind": "click", "label": "create"}
    ]

    # レシピから（強調を当てた絵を作りながらシートにする）
    python cue_stills.py recipe.json --src-dir ./raw --out-dir ./work/stills --sheets

    # すでに加工済みのフレームから
    python cue_stills.py --frame-dir ./work/frames --out-dir ./work/stills --sheets

注意: シートに焼く見出しは **ASCII だけ**にしている。等幅のビットマップフォントは
日本語グリフを持たず、豆腐や `?????` になるため。見出しはファイル名と座標で足りる。
"""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

try:  # 同じディレクトリの redact.py を使い回す（強調の描き方を1か所に保つ）
    from redact import blackout, highlight
except ImportError:  # スクリプトを別の場所から呼んだとき
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from redact import blackout, highlight

CAPTION_H = 26
CAPTION_BG = (24, 24, 28)
CAPTION_FG = (235, 235, 235)
SHEET_BG = (12, 12, 14)
GAP = 6
IMG_EXT = (".png", ".jpg", ".jpeg", ".webp")


def ascii_only(s: str) -> str:
    """見出し用。非 ASCII は落とす（豆腐になるより消えたほうが読める）。"""
    return re.sub(r"[^\x20-\x7e]", "", s).strip()


def natural_key(p: Path):
    return [int(t) if t.isdigit() else t.lower() for t in re.split(r"(\d+)", p.name)]


def render_from_recipe(recipe: Path, src_dir: Path, out_dir: Path,
                       dim: float, quality: int, save_stills: bool):
    """レシピを読み、強調を当てた画像とその見出しを返す。"""
    steps = json.loads(recipe.read_text(encoding="utf-8"))
    items = []
    for i, s in enumerate(steps, 1):
        im = Image.open(src_dir / s["src"]).convert("RGB")
        if s.get("blackout"):
            im = blackout(im, s["blackout"])
        box = s.get("highlight")
        if box:
            im = highlight(im, box, s.get("dim", dim))
        cap = f"{i:02d} {ascii_only(s['out'])}"
        if box:
            cap += "  cue " + ",".join(str(int(v)) for v in box)
            kind = ascii_only(str(s.get("kind", "")))
            if kind:
                cap += f" [{kind}]"
        else:
            cap += "  (no cue)"
        if save_stills:
            dst = out_dir / s["out"]
            dst.parent.mkdir(parents=True, exist_ok=True)
            if dst.suffix.lower() in (".jpg", ".jpeg"):
                im.save(dst, "JPEG", quality=quality)
            else:
                im.save(dst)
        items.append((im, cap, bool(box)))
    return items


def load_frames(frame_dir: Path):
    files = sorted((f for f in frame_dir.iterdir()
                    if f.suffix.lower() in IMG_EXT), key=natural_key)
    if not files:
        raise SystemExit(f"画像が見つかりません: {frame_dir}")
    return [(Image.open(f).convert("RGB"), f"{i:02d} {ascii_only(f.name)}", True)
            for i, f in enumerate(files, 1)]


def cell(im: Image.Image, caption: str, w: int, font) -> Image.Image:
    h = max(1, round(im.height * w / im.width))
    small = im.resize((w, h), Image.LANCZOS)
    out = Image.new("RGB", (w, h + CAPTION_H), CAPTION_BG)
    out.paste(small, (0, CAPTION_H))
    ImageDraw.Draw(out).text((6, 6), caption, fill=CAPTION_FG, font=font)
    return out


def build_sheets(items, out_dir: Path, per_sheet: int, cols: int,
                 cell_w: int, quality: int):
    font = ImageFont.load_default()
    sheets = []
    for n, start in enumerate(range(0, len(items), per_sheet), 1):
        chunk = items[start:start + per_sheet]
        cells = [cell(im, cap, cell_w, font) for im, cap, _ in chunk]
        rows = (len(cells) + cols - 1) // cols
        cw = max(c.width for c in cells)
        ch = max(c.height for c in cells)
        sheet = Image.new("RGB",
                          (cols * cw + (cols + 1) * GAP,
                           rows * ch + (rows + 1) * GAP), SHEET_BG)
        for i, c in enumerate(cells):
            x = GAP + (i % cols) * (cw + GAP)
            y = GAP + (i // cols) * (ch + GAP)
            sheet.paste(c, (x, y))
        dst = out_dir / f"sheet{n:02d}.jpg"
        sheet.save(dst, "JPEG", quality=quality)
        first, last = start + 1, start + len(chunk)
        print(f"  {dst.name}  {sheet.size}  frames {first}-{last}")
        sheets.append(dst)
    return sheets


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("recipe", type=Path, nargs="?",
                    help="redact.py と同じレシピ JSON")
    ap.add_argument("--src-dir", type=Path, default=Path("."),
                    help="レシピの src を探すディレクトリ")
    ap.add_argument("--frame-dir", type=Path, default=None,
                    help="加工済みフレームのディレクトリ（レシピの代わり）")
    ap.add_argument("--out-dir", type=Path, required=True)
    ap.add_argument("--sheets", action="store_true",
                    help="コンタクトシートを作る（既定はこちらを使う）")
    ap.add_argument("--stills", action="store_true",
                    help="原寸の静止画も書き出す（怪しい1枚を確かめる用）")
    ap.add_argument("--per-sheet", type=int, default=4)
    ap.add_argument("--cols", type=int, default=2)
    ap.add_argument("--cell-width", type=int, default=760)
    ap.add_argument("--dim", type=float, default=0.45,
                    help="強調の外側を暗くする強さ。実測の最適値は 0.45")
    ap.add_argument("--quality", type=int, default=88)
    a = ap.parse_args()

    if bool(a.recipe) == bool(a.frame_dir):
        raise SystemExit("レシピ(JSON) か --frame-dir の**どちらか一方**を指定してください")

    a.out_dir.mkdir(parents=True, exist_ok=True)
    if a.recipe:
        items = render_from_recipe(a.recipe, a.src_dir, a.out_dir,
                                   a.dim, a.quality, a.stills or not a.sheets)
    else:
        items = load_frames(a.frame_dir)

    print(f"■ cue-stills: {len(items)}枚")
    no_cue = [cap for _, cap, has in items if not has]
    if no_cue:
        print(f"  強調なし {len(no_cue)}枚: " + ", ".join(c.split()[0] for c in no_cue))

    if a.sheets:
        sheets = build_sheets(items, a.out_dir, a.per_sheet, a.cols,
                              a.cell_width, a.quality)
        print(f"\n{len(sheets)} 枚のコンタクトシートを {a.out_dir} に書き出しました。")
        print("  ※ 全シートを見る（抜き取りでは当たらない）。"
              "怪しい1枚だけ原寸で開いて確かめる")
        print("  見るところ: 枠が台本の言う対象を囲んでいるか / "
              "横長のフィールドで左端に寄っているか / ラベルが画面外に出ていないか")
    else:
        print(f"\n{len(items)} 枚を {a.out_dir} に書き出しました。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
