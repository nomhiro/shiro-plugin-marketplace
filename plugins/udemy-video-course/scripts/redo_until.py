"""誤読した行を、STT で『読めた』と判定できるまで作り直す（読めた時点で止める。読めた版を上書きしない）。

    python redo_until.py <unit-slug> <frame> --need 語1,語2 [--ban 語3,語4] [--max 6]

--need: STT の書き起こしに**全部入っている**こと（小文字化・空白除去で比べる。例: auc,過学習）
--ban : 入っていてはいけない語（誤読の綴り。例: 英雄,競売）
tts.py は `--only <frame>` で呼ぶ（他の行は据え置き）。check_reading.py は `--frame` で1行だけ見る。
最大 --max 回で諦めて、最後の版を残し、終了コード 2（耳で確かめる語として報告する）。
作り直したあとの pad_audio・check_clicks・make_beats・sync-durations・dump_beats は手でやる。
"""
import argparse
import re
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import course_config  # noqa: E402


def norm(s: str) -> str:
    return re.sub(r"\s+", "", s).lower()


def main(argv):
    ap = argparse.ArgumentParser()
    ap.add_argument("unit")
    ap.add_argument("frame", type=int)
    ap.add_argument("--need", default="")
    ap.add_argument("--ban", default="")
    ap.add_argument("--max", type=int, default=6)
    a = ap.parse_args(argv[1:])
    need = [norm(x) for x in a.need.split(",") if x]
    ban = [norm(x) for x in a.ban.split(",") if x]
    env = {"PYTHONIOENCODING": "utf-8"}
    import os
    env = {**os.environ, **env}
    proj = str(course_config.load().unit(a.unit))
    for i in range(1, a.max + 1):
        subprocess.run([sys.executable, str(HERE / "tts.py"), proj, "--only", str(a.frame)],
                       capture_output=True, env=env)
        out = subprocess.run([sys.executable, str(HERE / "check_reading.py"), proj, "--frame", str(a.frame)],
                             capture_output=True, text=True, encoding="utf-8", env=env).stdout
        line = next((l for l in out.splitlines() if re.match(rf"\s*{a.frame}\s", l)), "")
        n = norm(line)
        ok = all(x in n for x in need) and not any(x in n for x in ban)
        print(f"try {i}: {'OK' if ok else 'NG'}  {line.strip()[:200]}")
        if ok:
            return 0
    print("読めた版が得られなかった（最後の版を残した）→ 耳で確かめる語として報告する")
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv))
