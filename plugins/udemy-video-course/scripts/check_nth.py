"""slides.py の E(フレーム, "語", nth) のうち、語が beats に2回以上出るものを一覧にする（読み取り専用）。

    python check_nth.py videos/<unit> [videos/<unit2> ...]

2026-10-18 新設（L2-1 末尾 F2 で E(2, "通っ") が1回目「フィルターを通ってから」を引き、結論の箱が15秒早く出た。
slide-reviewer 観点18「早すぎる表示」の再発）。check_late_reveals は遅いほうしか見ないので、早いほうをここで拾う。
出力は候補。選んだ回（★）が、その要素を語る文の頭の語かを目で確かめる。
"""
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from slide_kit import Beats  # noqa: E402

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, OSError):
        pass

CALL = re.compile(r'E\((\d+),\s*"([^"]+)"(?:,\s*(?:nth=)?(\d+))?\)')   # 2026-10-21 L4-3 slide-reviewer: nth= をキーワードで渡した呼び出しも拾う


def hits(E, frame, phrase):
    toks = E.tok.get(frame, [])
    out = []
    for i in range(len(toks)):
        acc, j = "", i
        while j < len(toks) and len(acc) < len(phrase):
            acc += toks[j][0]
            j += 1
        if acc == phrase:
            out.append(toks[j - 1][1])
    return out


def main(argv):
    n = 0
    for d in argv[1:]:
        unit = Path(d)
        E = Beats(unit)
        src = (unit / "slides.py").read_text(encoding="utf-8")
        seen = set()
        for ln, line in enumerate(src.splitlines(), 1):
            for m in CALL.finditer(line):
                f, ph, nth = int(m.group(1)), m.group(2), int(m.group(3) or 0)
                hs = hits(E, f, ph)
                if len(hs) > 1 and (f, ph, nth) not in seen:
                    seen.add((f, ph, nth))
                    n += 1
                    times = " ".join(("★" if k == nth else "") + f"{t:.1f}" for k, t in enumerate(hs))
                    print(f"  {unit.name} F{f} L{ln}: 「{ph}」 nth={nth}  回: {times}")
    print(f"同じ語が2回以上出る E(): {n} 件（★＝選んだ回。語る文の頭か目で確かめる）")


if __name__ == "__main__":
    main(sys.argv)
