"""行の詰まり検査（デジタル庁デザインシステムの転用・2026-10-09）。

    python check_spacing.py videos/<unit> [videos/<unit2> ...]
    python check_spacing.py --all            # <videos_dir>/*/compositions/frames を全部

同じ列（x の揃い）に積んだ文字の「行送り ÷ 文字の高さ」を測り、**1.25 倍未満**（文の行どうしは **1.4 倍未満**。2026-10-18）を出す（DADS は本文 1.5 倍・データ 1.2〜1.3 倍。スライドの積み文字は 1.3 以上を目安）。
- 行送り ÷ 2行の文字の高さの平均（font-size）。行送り = y の差
- 大きさが 30% 以上違う組（TP と 80 のような「見出しと数」）は意図した対とみなして除く
- 同じ x の揃えで、行送りが文字の高さの 0.6 倍未満の組は「別の列（横並び）」とみなして除く
出力は**候補**。目で見て、直すか（行を離す・カードに分ける）、意図した詰めかを決める。
"""
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import course_config  # noqa: E402

TEXT = re.compile(r'<text class="([^"]*)" x="([\d.]+)" y="([\d.]+)" text-anchor="(\w+)" style="font-size:([\d.]+)cqw"[^>]*>([^<]*)</text>')
CQW = 19.2
LIMIT = 1.25
# （2026-10-18 L1-2 再レビューの提案・ユーザー承認）: 文の行（句読点を含み 12字以上）が続くときは 1.4 倍を目安にする（DADS の本文寄り）
LIMIT_SENTENCE = 1.4


def _sentence(body: str) -> bool:
    return len(body) >= 12 and any(c in body for c in "、。")


def check(path: Path):
    html = path.read_text(encoding="utf-8")
    items = []
    for m in TEXT.finditer(html):
        cls, x, y, anchor, size, body = m.groups()
        items.append((float(x), float(y), anchor, float(size) * CQW, body))
    out = []
    for i, (x1, y1, a1, s1, b1) in enumerate(items):
        for x2, y2, a2, s2, b2 in items[i + 1:]:
            if a1 != a2 or abs(x1 - x2) > 6 or y2 <= y1:
                continue
            big, small = max(s1, s2), min(s1, s2)
            if (big - small) / big >= 0.3:
                continue
            pitch = y2 - y1
            ratio = pitch / ((s1 + s2) / 2)
            limit = LIMIT_SENTENCE if _sentence(b1) and _sentence(b2) else LIMIT
            if 0.6 <= ratio < limit:
                out.append((ratio, pitch, b1, b2))
    return out


def main(argv):
    if not argv:
        print(__doc__)
        return 2
    if argv == ["--all"]:
        dirs = sorted(p.parent.parent for p in course_config.load().videos.glob("*/compositions/frames"))
    else:
        dirs = [Path(a) for a in argv]
    total = 0
    for d in dirs:
        frames = sorted((d / "compositions" / "frames").glob("*.html"))
        hits = []
        for f in frames:
            for ratio, pitch, b1, b2 in check(f):
                hits.append(f"  {f.name}: {ratio:.2f}倍（{pitch:.0f}px）「{b1}」→「{b2}」")
        total += len(hits)
        print(f"{d.name}: 詰まり候補 {len(hits)} 件")
        for h in hits:
            print(h)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
