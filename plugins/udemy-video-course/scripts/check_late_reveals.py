"""「話し終わりで強調される」を拾う検査（2026-10-09・ユーザー指摘「00:37あたり、強調が話し終わりくらいの時。話し始めの時に強調すべき」）。

    python check_late_reveals.py videos/<unit> [videos/<unit2> ...]
    python check_late_reveals.py --all

slides.py の `E(frame, "語")` の着地時刻（＝その語の語末）が、その語を含む**ひと続きの発話の頭**から何秒遅れているかを測る。
- ひと続き ＝ 語と語のあいだが 0.9 秒未満で続く範囲（文の切れ目・読点の長い間で切る）
- 遅れ ≥ LIMIT（既定 2.5 秒）を出す。**候補**。見て決める:
  ・要素が「その発話の終わりの語」そのもの（結果の数・答え）なら語末でよい
  ・長い説明の行・箇条を強調する着地なら、**その発話の頭（最初の語の語末）に前倒しする**
"""
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import course_config  # noqa: E402
from slide_kit import Beats  # noqa: E402

CALL = re.compile(r'E\((\d+),\s*"([^"]+)"(?:,\s*(\d+))?\)')
GAP = 0.9
LIMIT = 2.5


def lateness(beats, frame, phrase, nth):
    toks = beats.tok[frame]
    at = beats(frame, phrase, nth)
    idx = next(i for i, (_, t) in enumerate(toks) if abs(t - at) < 1e-6)
    j = idx
    while j > 0 and toks[j][1] - toks[j - 1][1] < GAP + 0.0 and (j - 1) >= 0:
        j -= 1
    # j = 発話の最初の語。その語末が「頭」
    return at - toks[j][1], toks[j][1], at


def main(argv):
    if not argv:
        print(__doc__)
        return 2
    dirs = sorted(p.parent for p in course_config.load().videos.glob("*/slides.py")) if argv == ["--all"] else [Path(a) for a in argv]
    for d in dirs:
        src = d / "slides.py"
        if not src.exists():
            continue
        try:
            beats = Beats(d)
        except Exception:
            continue
        hits = []
        for lineno, line in enumerate(src.read_text(encoding="utf-8").splitlines(), 1):
            for m in CALL.finditer(line):
                fr, ph, nth = int(m.group(1)), m.group(2), int(m.group(3) or 0)
                try:
                    late, start, at = lateness(beats, fr, ph, nth)
                except Exception:
                    continue
                if late >= LIMIT:
                    hits.append((fr, late, start, at, ph, lineno))
        print(f"{d.name}: 遅い強調の候補 {len(hits)} 件")
        for fr, late, start, at, ph, ln in hits:
            print(f"  F{fr} L{ln}: 「{ph}」 着地 {at:.1f}s（発話の頭 {start:.1f}s から +{late:.1f}s）")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
