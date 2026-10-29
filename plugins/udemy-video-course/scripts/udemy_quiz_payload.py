# -*- coding: utf-8 -*-
"""小テスト（Udemy のクイズ＝simple-quiz）の問題を、Udemy の API にそのまま送れる本文に変える。

演習テスト（practice test）は CSV の一括アップロードがあるが、動画講座の**クイズ**には無い。
1問ずつ `POST /api-2.0/quizzes/<quizId>/assessments/` で入れる。その本文を作るのがこのスクリプト
（送るのはブラウザ内のスクリプト。手順は publish-video-course スキル）。

    python udemy_quiz_payload.py quizzes.json -o quiz_import.json

入力（講座側の原稿から作る。原稿の書式は講座ごとに違うので、パーサは講座側に置く）:

    [{"slug": "L1-1_quiz", "title": "<主題>：確認テスト", "description": "…",
      "questions": [{"id": "L1-1-Q1", "question": "本文", "options": ["…", "…", "…", "…"],
                     "correct": 0, "explanation": "解説"}]}]

出力: 同じ並びで、各問に `body`（assessments に送る JSON）を足したもの。

判定（どれかに当たれば止める）: 選択肢が 2〜6 でない／正解の番号が範囲外／本文・解説が空。
本文・選択肢・解説の `**太字**` は外す（クイズでは記号のまま出る）。1 行を 1 段落に、`- ` の行は箇条書きにし、
`<` `>` `&` はエスケープする。
選択肢ごとの解説（feedbacks）は「正解です。」／「不正解です。」＋解説全文にする（どの選択肢を選んでも理由が読める）。

原稿（Markdown）から直接読むこともできる（ハンズオン中心の講座の小テストの原稿の形）:

    python udemy_quiz_payload.py --from-md lectures/04_ide/L4-1_quiz.md -o quiz_import.json --qs qs.json

    ## 問題
    ### Q1
    問いの文（1段落）
    - A. 選択肢 ← **正解**
    - B. 選択肢
    **解説**：解説の文

`## 問題` の節だけを読む（後ろの「保留案」「参照」の節を読むと、同じ番号の問いが重なって入る）。

`--qs` を付けると、画面の操作で入れるための `window.__QS`（`[{a: 正解の位置, s: 問い, o: [選択肢], e: 解説}]`）を
小テストごとに書き出す（`templates/udemy_quiz_helpers.js` が読む形）。画面で入れる文は書式なしなので、
`**太字**` と `` `コード` `` の記号を外す（中の語は残す）。

終了コード: 0＝書き出した／1＝検証に落ちた問題がある（書き出さない）。
"""
from __future__ import annotations

import argparse
import html
import json
import re
import sys
from pathlib import Path

LETTERS = "abcdef"


def _esc(s: str) -> str:
    return html.escape(s, quote=False)


def to_html(text: str) -> str:
    """1 行を 1 段落に、`- ` で始まる行の並びを箇条書きにする（ア／イの列挙が崩れずに出た形）。"""
    out, bullets = [], []

    def flush():
        if bullets:
            out.append("<ul>" + "".join(f"<li><p>{_esc(b)}</p></li>" for b in bullets) + "</ul>")
            bullets.clear()

    for ln in text.replace("**", "").split("\n"):
        ln = ln.strip()
        if not ln:
            flush()
        elif ln.startswith("- "):
            bullets.append(ln[2:].strip())
        else:
            flush()
            out.append(f"<p>{_esc(ln)}</p>")
    flush()
    return "".join(out) or "<p></p>"


def problems(q: dict) -> list[str]:
    out = []
    n = len(q.get("options") or [])
    if not 2 <= n <= 6:
        out.append(f"選択肢が {n}")
    c = q.get("correct")
    if not isinstance(c, int) or not 0 <= c < n:
        out.append(f"正解の番号が範囲外（{c}）")
    if not (q.get("question") or "").strip():
        out.append("本文が空")
    if not (q.get("explanation") or "").strip():
        out.append("解説が空")
    return out


def body(q: dict) -> dict:
    """assessments に送る本文。answers・feedbacks・correct_response は JSON 文字列で送る（Udemy の API の形）。"""
    expl = to_html(q["explanation"])
    feedbacks = [("<p>正解です。</p>" if i == q["correct"] else "<p>不正解です。</p>") + expl
                 for i in range(len(q["options"]))]
    return {
        "assessment_type": "multiple-choice",
        "question": to_html(q["question"]),
        "answers": json.dumps([to_html(o) for o in q["options"]], ensure_ascii=False),
        "feedbacks": json.dumps(feedbacks, ensure_ascii=False),
        "correct_response": json.dumps([LETTERS[q["correct"]]]),
        "related_lecture": "",
        "explanation": "",
        "section": "",
        "section_name_map": "[]",
    }


def _plain(t: str) -> str:
    """画面の入力欄は書式なし。`**` と バッククォートの記号を外す（中の語は残す）。"""
    return re.sub(r"`([^`]*)`", r"\1", t.replace("**", "")).strip()


def parse_md(md: str, slug: str = "", title: str = "") -> dict:
    """小テストの原稿（`## 問題` の下に `### Qn`）を、このスクリプトの入力の形にする。"""
    m = re.search(r"^## 問題\s*$", md, re.M)
    if m:
        body_md = md[m.end():]
        n = re.search(r"^## ", body_md, re.M)
        body_md = body_md[:n.start()] if n else body_md
    else:
        body_md = md
    questions = []
    for blk in re.split(r"(?m)^### ", body_md)[1:]:
        head, _, rest = blk.partition("\n")
        qm = re.match(r"Q(\d+)", head)
        if not qm:
            continue
        stem, opts, correct, expl = [], [], None, ""
        for ln in rest.splitlines():
            om = re.match(r"-\s*([A-F])[.．]\s*(.+?)(\s*←\s*\**正解.*)?$", ln)
            em = re.match(r"\*\*解説\*\*\s*[：:]\s*(.+)", ln)
            if om:
                if om.group(3):
                    correct = len(opts)
                opts.append(om.group(2).strip())
            elif em:
                expl = em.group(1).strip()
            elif ln.strip() and not opts and not ln.startswith(">"):
                stem.append(ln.strip())
        questions.append({"id": f"{slug}-Q{qm.group(1)}", "question": "\n".join(stem),
                          "options": opts, "correct": correct, "explanation": expl})
    if not title:
        h = re.search(r"^# (.+)$", md, re.M)
        title = h.group(1).strip() if h else slug
    return {"slug": slug, "title": title, "description": "", "questions": questions}


def to_qs(q: dict) -> dict:
    """画面の操作で入れる1問（templates/udemy_quiz_helpers.js の window.__QS の要素）。"""
    return {"a": q["correct"], "s": _plain(q["question"]),
            "o": [_plain(o) for o in q["options"]], "e": _plain(q["explanation"])}


def main() -> int:
    for s in (sys.stdout, sys.stderr):
        try:
            s.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, OSError):
            pass
    ap = argparse.ArgumentParser()
    ap.add_argument("src", type=Path, nargs="?", help="quizzes.json（--from-md のときは要らない）")
    ap.add_argument("--from-md", type=Path, nargs="+", default=None,
                    help="小テストの原稿（Markdown）から直接読む")
    ap.add_argument("-o", "--out", type=Path, required=True)
    ap.add_argument("--qs", type=Path, default=None,
                    help="画面の操作で入れるための window.__QS を小テストごとに書き出す")
    a = ap.parse_args()
    if a.from_md:
        quizzes = [parse_md(p.read_text(encoding="utf-8"), slug=p.stem) for p in a.from_md]
    elif a.src:
        quizzes = json.loads(a.src.read_text(encoding="utf-8"))
    else:
        ap.error("quizzes.json か --from-md を渡す")
    bad, pos, n = 0, [0] * 6, 0
    for qz in quizzes:
        for q in qz["questions"]:
            why = problems(q)
            if why:
                bad += 1
                print(f"  NG {q.get('id')}: {'／'.join(why)}")
                continue
            q["body"] = body(q)
            pos[q["correct"]] += 1
            n += 1
    if bad:
        print(f"■ {bad} 問が検証に落ちた（書き出していない）")
        return 1
    a.out.write_text(json.dumps(quizzes, ensure_ascii=False, indent=1), encoding="utf-8")
    if a.qs:
        a.qs.write_text(json.dumps({qz["slug"]: [to_qs(q) for q in qz["questions"]] for qz in quizzes},
                                   ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"  画面の操作用の __QS → {a.qs}")
    print(f"■ クイズ {len(quizzes)} 本・{n} 問 → {a.out}")
    print("  正解の位置（a..f）:", pos, "← 偏りが大きければ原稿で入れ替える")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
