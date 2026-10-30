"""`crossfade` で受けるフレームが、継ぎ目で二重像にならないかを機械で検査する。

## なぜ必要か

2026-09-18、3-1-1（分類と回帰）の frame 7・frame 9 が**どちらも同じ違反**を抱えていた。
`transition_in: crossfade` のフレームなのに、**0 〜 0.5 秒の窓の中で tween が動いていた**。
crossfade の窓は**前後2枚が同時に画面にある**ので、入ってくる側が動いていると
**前フレームの静止画に、動いている自分が重なる**。`lint` も `check` も検出しない。

**さらに、当初の規則「0〜0.5s に tween を置かない」では不十分だった。**

> frame 7 の上段の印は `tl.fromTo(markA, {scale: 0.92}, {scale: 1}, 0.06)` だった。
> これを 0.56 へずらしても**直らない**。`fromTo` の既定は `immediateRender: true` で
> **構築した瞬間に `from` を書き込む**ので（CLAUDE.md 規則2）、
> **t=0 の markA は scale 0.92 のまま**になる。前フレーム（frame 6）の同じ位置の印
> （`.f06-tick-a` / `.f06-tick-b`。transform の tween を1本も持たない = scale 1）と
> 食い違い、**44px の印が 40.48px で重なる状態が 0.5 秒続く**。
> `immediateRender: false` にすると t=0 は正しくなるが、**今度は 0.56 でスナップする**
> （後方 seek でも `from` が書き戻るので seek-safe でもない）。

したがって規則はこう書き直された。

> **`crossfade` で受けるフレームは、前フレームの終端と値が違うプロパティを
> そもそもアニメーションできない。** 開始時刻をずらしても `from` が t=0 に出る。
> **検算は「開始時刻 ≥ 窓」だけでは不十分**で、
> **t=0 に書かれる `from` の値が前フレームの終端と一致すること**まで確かめる。

解は「`from` を前フレームの終端と同じ値にする」こと。frame 7 は印の所作を
`{scale: 0.92} → {scale: 1}` から **`{scale: 1} → {scale: 0.96} → {scale: 1}`** に変えた。
タイミング（開始 0.56 / 全長 0.56 / 着地 1.12 / 戻りの ease `power3.out`）は据え置き。

**修正後の実測**（親の `snapshot` / 局所時刻と印の実寸）:

| 局所 t | 印の実測 | 意味 |
|---|---|---|
| 0.094 / 0.294 / 0.494 | **44.00 × 44.00** | 窓の中。frame 6 と一致 ✓ |
| 0.744 | 43.00 | パルスが効いている ✓ |
| 1.194 / 1.494 | 44.00 | 着地後 ✓ |

窓の中ではブロブ走査でも印が1つしか検出されない（2枚が完全に重なっている）。

**このファイルはその検算を機械にやらせる。** 残り 136 ユニット × 約9枚あり、
`crossfade` で受けるフレームはその半分近い。目視でも報告でも追いきれない。

## 3つの検査

1. **`transition_window`** — 窓（前フレームのはみ出し尺）の中で始まる tween が無いか
2. **`t0_from_state`** — t=0 に書き込まれる状態。`fromTo` / `from` の `from` 引数
   （`immediateRender: false` が付いていないもの）と、**`tl.set(..., 0)` の vars**。
   transform の非中立値は**前フレームが同名プロパティを一切動かしていなければ
   確定で不一致**（前フレームは中立＝`scale` 1 / `x` `y` `rotation` 0 にいるため）。
   ★ **`tl.set(..., 0)` は「動き」ではないので窓の検査には掛けない** —— 位置 0 で
   即座に当たるので二重像の原因にはならない。ただし**その値は t=0 の絵に出る**ので、
   状態としては突き合わせる（位置が 0 より後の `set` は窓の中で跳ねるので ERROR）
3. **`clip_duration`** — ルートと内側の `class="clip"` の `data-duration` が全部同値か
   （CLAUDE.md サブエージェント項目1。旧尺のまま残った clip は地の色すら無い白で終わる）

## ★ 完全自動ではない。「人が見るべきもの」を列挙する道具

`from` の値が CSS 変数や実行時の値を経由していると**静的には解けない**。
解けなかったものは **`REVIEW`** として**必ず列挙する**（黙って通さない）。
**完全性より、見落としを作らないことを優先している。**

窓の長さは `index.html` から導く（**秒数を決め打ちしない**）:

    窓 = (前フレームの data-start + data-duration) − 自分の data-start

`transitions.mjs inject` が前フレームの尺を 0.5 秒だけ伸ばすので、この差がそのまま窓になる。
`STORYBOARD.md` の `- transition_in:` とも突き合わせ、食い違えばそれ自体を報告する。

## ★ 8g を当てるのは `crossfade` だけ

**`crossfade` と `push-slide` は重なり方が違う。**

- **`crossfade`** … 2枚が**同じ場所に重なって**溶暗する
  → 同じ要素の値がずれていると**二重像**になる。**8g の対象**
- **`push-slide`** … 2枚が**並んで平行移動**する（カルーセル）
  → **前の絵が新しい絵に重ならない。** 窓の中で中身が動いても二重像にはならない。
    窓があることだけ `[info]` で見せて、検査は当てない
- **`cut`** … 窓そのものが無い（`[skip]`）

`transition_in` が `STORYBOARD.md` から読めなかったフレームは、**安全側に倒して検査する**
（`?` として REVIEW にも出す）。

## ★ `index.html` が未組み立てでも検査する

**`assemble-index` は全フレームが揃ってから走る。** つまり**制作中はずっと
`index.html` が空**で、**検査を回したい時期と、実測の窓が取れない時期が完全に重なる。**

> **実測（2026-09-18・3-1-3）**: `videos/logistic-regression` は `07-still.html` が
> ディスクに在るのに `index.html` が未組み立てで、**「検査対象なし」＋「問題なし。」＋
> exit 0** を返していた。**1バイトも検査していないのに成功として通っていた。**

だから `index.html` からフレームを取れないときは **`STORYBOARD.md` の順番**に落ちて、
**窓を既定の 0.5s と仮定して**検査する（`transitions inject` の規約は固定なので安全）。
前フレームは**ストーリーボードで1つ前**のもの。それがディスクに無ければ、
`t0_from_state` の突き合わせだけ REVIEW に落とす。

**出力には「仮定」と明示する。** そして**フレームが在るのに1枚も検査できなかったときは
「問題なし」と言わず、exit も 0 にしない**（`BLOCKED` として数える）。

| 状態 | 出力 |
|---|---|
| フレーム 0枚 | 「検査対象なし」・exit 0 |
| **フレームは在る / `index.html` 未組み立て** | **仮定の窓で検査。できなければ BLOCKED＋非0** |
| フレームも `index.html` も在る | 実測の窓で検査 |

## 使い方

    python check_crossfade.py videos/supervised-classification-regression
    python check_crossfade.py videos/*          # 全ユニット
    python check_crossfade.py videos/... --strict  # REVIEW でも 1 を返す

終了コードは、ERROR があれば 1（`--strict` なら REVIEW でも 1）。
ブラウザは起動しない。静的解析だけ。
"""

from __future__ import annotations

import argparse
import ast
import re
import sys
from pathlib import Path

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, OSError):
        pass

# GSAP の transform プロパティと、その「中立（何もしていない）」値。
# 前フレームが同名プロパティを一切動かしていなければ、前フレームはこの値にいる。
TRANSFORM_NEUTRAL = {
    "scale": 1.0, "scaleX": 1.0, "scaleY": 1.0,
    "x": 0.0, "y": 0.0, "z": 0.0,
    "xPercent": 0.0, "yPercent": 0.0,
    "rotation": 0.0, "rotate": 0.0, "rotationX": 0.0, "rotationY": 0.0,
    "skewX": 0.0, "skewY": 0.0,
}
# 窓の中で動いてよい猶予（秒）。丸め誤差だけを吸収する。
EPS = 1e-6
# `index.html` が未組み立てのときに仮定する窓。`transitions.mjs inject` の規約値。
ASSUMED_WINDOW = 0.5
# 「見た目の状態」ではないので t=0 の突き合わせから外すキー。
# transformOrigin は scale 1 では絵に出ない（scale と一緒に出てきたときだけ意味を持つ）。
NON_STATE_KEYS = {
    "duration", "ease", "delay", "immediateRender", "overwrite", "stagger",
    "onUpdate", "onComplete", "onStart", "onReverseComplete", "repeat", "yoyo",
    "transformOrigin", "svgOrigin", "transformPerspective", "force3D", "id",
}


def invisible_at_t0(from_obj: dict[str, str], env: dict) -> str | None:
    """t=0 でその要素が**見えていない**なら、その理由を返す。

    見えていない要素の transform のずれは**絵に出ない**ので、
    crossfade の窓の検査対象にしてはいけない（ここを見落とすと偽陽性だらけになる。
    実測: 3-1-1 の frames 3・5 で `{opacity: 0, y: 18}` のような「新しく出てくる要素」が
    9件すべて誤検出された）。
    """
    for key in ("opacity", "autoAlpha"):
        v = js_eval(from_obj.get(key, ""), env)
        if v is not None and abs(v) < 1e-9:
            return "%s: 0" % key
    for key in ("scale", "scaleX", "scaleY"):
        v = js_eval(from_obj.get(key, ""), env)
        if v is not None and abs(v) < 1e-9:
            return "%s: 0" % key
    return None


def target_hidden_at_t0(props: dict[str, list[str]], env: dict) -> str | None:
    """**要素ごとに集めた** t=0 の書き込みから、その要素が見えていないかを判定する。

    ★ `{opacity: 0}` を書く呼び出しと transform を書く呼び出しは**別のことがある**。

        tl.set("#f05-plane-back", { opacity: 0, x: BACK_DX, y: BACK_DY }, 0);
        tl.fromTo("#f05-plane-back", { x: BACK_DX, y: BACK_DY }, { x: 0, y: 0 }, W.SARANI);

    2本目だけを見ると「x が中立から -46.4 ずれている」に見えるが、
    **1本目で opacity 0 にされているので t=0 では見えていない**（3-1-2 frame 5 の実例）。
    呼び出し単位ではなく**要素単位**で見ないと、この形を誤検出する。

    値が食い違うとき（0 と非0 が混在）は**不可視と断定しない** —— 静的には順序が
    決まらないので、安全側に倒して検査対象のまま残す。
    """
    for group in (("opacity", "autoAlpha"), ("scale", "scaleX", "scaleY")):
        for key in group:
            vals = [js_eval(v, env) for v in props.get(key, [])]
            vals = [v for v in vals if v is not None]
            if vals and all(abs(v) < 1e-9 for v in vals):
                return "%s: 0" % key
    return None


# ────────────────────────────────────────────────────────────────────────────
# JS の下ごしらえ
# ────────────────────────────────────────────────────────────────────────────
def strip_js_comments(js: str) -> str:
    """コメントを空白に置き換える。**オフセットは変えない**（span を後で使うため）。"""
    out = list(js)
    i, n = 0, len(js)
    quote = None
    while i < n:
        c = js[i]
        if quote:
            if c == "\\":
                i += 2
                continue
            if c == quote:
                quote = None
            i += 1
            continue
        if c in "\"'`":
            quote = c
            i += 1
            continue
        if c == "/" and i + 1 < n and js[i + 1] == "*":
            j = js.find("*/", i + 2)
            j = n if j < 0 else j + 2
            for k in range(i, j):
                if out[k] != "\n":
                    out[k] = " "
            i = j
            continue
        if c == "/" and i + 1 < n and js[i + 1] == "/":
            j = js.find("\n", i)
            j = n if j < 0 else j
            for k in range(i, j):
                out[k] = " "
            i = j
            continue
        i += 1
    return "".join(out)


def match_balanced(text: str, open_at: int) -> int:
    """`text[open_at]` の括弧に対応する閉じ括弧の位置を返す（文字列リテラルを無視する）。"""
    pairs = {"(": ")", "{": "}", "[": "]"}
    close = pairs[text[open_at]]
    opener = text[open_at]
    depth, i, n, quote = 0, open_at, len(text), None
    while i < n:
        c = text[i]
        if quote:
            if c == "\\":
                i += 2
                continue
            if c == quote:
                quote = None
        elif c in "\"'`":
            quote = c
        elif c == opener:
            depth += 1
        elif c == close:
            depth -= 1
            if depth == 0:
                return i
        i += 1
    return -1


def split_args(text: str) -> list[str]:
    """最上位のカンマで引数を割る。"""
    args, depth, cur, quote = [], 0, [], None
    for c in text:
        if quote:
            cur.append(c)
            if c == quote:
                quote = None
            continue
        if c in "\"'`":
            quote = c
        elif c in "([{":
            depth += 1
        elif c in ")]}":
            depth -= 1
        elif c == "," and depth == 0:
            args.append("".join(cur).strip())
            cur = []
            continue
        cur.append(c)
    tail = "".join(cur).strip()
    if tail:
        args.append(tail)
    return args


# ────────────────────────────────────────────────────────────────────────────
# JS の式を安全に評価する（数値だけ。解けなければ None）
# ────────────────────────────────────────────────────────────────────────────
_ALLOWED_FUNCS = {"min": min, "max": max, "abs": abs, "round": round}


def js_eval(expr: str, env: dict) -> float | None:
    e = expr.strip().rstrip(";").strip()
    if not e:
        return None
    e = e.replace("Math.min", "min").replace("Math.max", "max")
    e = e.replace("Math.abs", "abs").replace("Math.round", "round")
    try:
        node = ast.parse(e, mode="eval").body
    except SyntaxError:
        return None

    def walk(nd):
        if isinstance(nd, ast.Constant) and isinstance(nd.value, (int, float)):
            return float(nd.value)
        if isinstance(nd, ast.Name):
            v = env.get(nd.id)
            return float(v) if isinstance(v, (int, float)) else None
        if isinstance(nd, ast.Attribute) and isinstance(nd.value, ast.Name):
            # `W.wakareme` / `VO.NARA` / `IN.swap` —— var W = { ... } を解決する
            obj = env.get(nd.value.id)
            v = obj.get(nd.attr) if isinstance(obj, dict) else None
            return float(v) if isinstance(v, (int, float)) else None
        if isinstance(nd, ast.Subscript) and isinstance(nd.value, ast.Name):
            arr = env.get(nd.value.id)
            idx = walk(nd.slice)
            if isinstance(arr, list) and idx is not None and 0 <= int(idx) < len(arr):
                return float(arr[int(idx)])
            return None
        if isinstance(nd, ast.UnaryOp) and isinstance(nd.op, (ast.UAdd, ast.USub)):
            v = walk(nd.operand)
            return None if v is None else (v if isinstance(nd.op, ast.UAdd) else -v)
        if isinstance(nd, ast.BinOp):
            a, b = walk(nd.left), walk(nd.right)
            if a is None or b is None:
                return None
            if isinstance(nd.op, ast.Add):
                return a + b
            if isinstance(nd.op, ast.Sub):
                return a - b
            if isinstance(nd.op, ast.Mult):
                return a * b
            if isinstance(nd.op, ast.Div):
                return None if b == 0 else a / b
            return None
        if isinstance(nd, ast.Call) and isinstance(nd.func, ast.Name):
            fn = _ALLOWED_FUNCS.get(nd.func.id)
            if fn is None or nd.keywords:
                return None
            vals = [walk(a) for a in nd.args]
            return None if any(v is None for v in vals) else float(fn(*vals))
        return None

    return walk(node)


_ARR_MAP = re.compile(
    r"^\[(?P<items>[^\]]*)\]\s*\.\s*map\s*\(\s*function\s*\(\s*(?P<p>[\w$]+)\s*(?:,[^)]*)?\)\s*\{"
    r"\s*return\s+(?P<body>.+?);?\s*\}\s*\)$",
    re.S,
)


def js_eval_array(expr: str, env: dict) -> list[float] | None:
    """`[a, b]` と `[a, b].map(function (t) { return t + X; })` を数値の配列にする。"""
    e = expr.strip().rstrip(";").strip()
    m = _ARR_MAP.match(e)
    if m:
        base = [js_eval(x, env) for x in split_args(m.group("items"))]
        if any(v is None for v in base):
            return None
        out = []
        for v in base:
            r = js_eval(m.group("body"), {**env, m.group("p"): v})
            if r is None:
                return None
            out.append(r)
        return out
    if e.startswith("[") and e.endswith("]"):
        vals = [js_eval(x, env) for x in split_args(e[1:-1])]
        return None if any(v is None for v in vals) else vals
    return None


def js_eval_object(expr: str, env: dict) -> dict | None:
    """`{ a: 1.2, b: 2.0 }` を数値の辞書にする（数値のキーだけ拾う）。"""
    e = expr.strip().rstrip(";").strip()
    if not (e.startswith("{") and e.endswith("}")):
        return None
    out: dict[str, float] = {}
    for part in split_args(e[1:-1]):
        if ":" not in part:
            continue
        k, v = part.split(":", 1)
        val = js_eval(v, env)
        if val is not None:
            out[k.strip().strip("\"'")] = val
    return out or None


_VAR = re.compile(r"\bvar\s+([A-Za-z_$][\w$]*)\s*=\s*", re.S)


def collect_vars(js: str, seed: dict) -> dict:
    """`var NAME = ...;` を上から順に解決する。解けないものは入れない。"""
    env = dict(seed)
    for m in _VAR.finditer(js):
        name, start = m.group(1), m.end()
        end = start
        depth, quote = 0, None
        while end < len(js):
            c = js[end]
            if quote:
                if c == "\\":
                    end += 2
                    continue
                if c == quote:
                    quote = None
            elif c in "\"'`":
                quote = c
            elif c in "([{":
                depth += 1
            elif c in ")]}":
                depth -= 1
            elif c == ";" and depth == 0:
                break
            end += 1
        rhs = js[start:end].strip()
        obj = js_eval_object(rhs, env)
        if obj is not None:
            env[name] = obj
            continue
        arr = js_eval_array(rhs, env)
        if arr is not None:
            env[name] = arr
            continue
        val = js_eval(rhs, env)
        if val is not None:
            env[name] = val
    return env


# ────────────────────────────────────────────────────────────────────────────
# forEach の文脈（ループ変数を束縛するため）
# ────────────────────────────────────────────────────────────────────────────
_FOREACH = re.compile(
    r"\b([A-Za-z_$][\w$]*)\s*\.\s*forEach\s*\(\s*function\s*\(\s*([\w$]+)\s*(?:,\s*([\w$]+)\s*)?\)\s*\{"
)


def collect_foreach(js: str, env: dict) -> list[dict]:
    loops = []
    for m in _FOREACH.finditer(js):
        brace = js.index("{", m.end() - 1)
        end = match_balanced(js, brace)
        if end < 0:
            continue
        loops.append({
            "array": env.get(m.group(1)),
            "array_name": m.group(1),
            "param": m.group(2),
            "index": m.group(3),
            "start": brace,
            "end": end,
            "body": js[brace + 1:end],
        })
    return loops


def enclosing_loops(loops: list[dict], pos: int) -> list[dict]:
    return sorted([lp for lp in loops if lp["start"] < pos < lp["end"]],
                  key=lambda lp: lp["end"] - lp["start"])


# ────────────────────────────────────────────────────────────────────────────
# tl の呼び出しを拾う
# ────────────────────────────────────────────────────────────────────────────
_CALL = re.compile(r"(?:\btl\s*\.|\)\s*\.)\s*(fromTo|from|to|set)\s*\(")


def collect_calls(js: str) -> list[dict]:
    calls = []
    for m in _CALL.finditer(js):
        open_at = js.index("(", m.end() - 1)
        close = match_balanced(js, open_at)
        if close < 0:
            continue
        args = split_args(js[open_at + 1:close])
        calls.append({"method": m.group(1), "args": args, "pos": m.start(),
                      "text": " ".join(js[m.start():close + 1].split())})
    return calls


def obj_props(text: str) -> dict[str, str]:
    """`{ a: 1, b: X }` を {名前: 生テキスト} にする。"""
    t = text.strip()
    if not (t.startswith("{") and t.endswith("}")):
        return {}
    out = {}
    for part in split_args(t[1:-1]):
        if ":" not in part:
            continue
        k, v = part.split(":", 1)
        out[k.strip().strip("\"'")] = v.strip()
    return out


def call_positions(call: dict, loops: list[dict], env: dict) -> tuple[list[float], str | None]:
    """呼び出しの開始時刻を返す。解けなければ (ここまで解けたもの, 未解決の生テキスト)。"""
    n_vars = {"fromTo": 3, "from": 2, "to": 2, "set": 2}[call["method"]]
    if len(call["args"]) <= n_vars:
        # 位置引数なし = タイムラインの末尾に積まれる。**空のタイムラインなら 0 から始まる**
        return [], "位置引数なし（末尾に積まれる。空なら 0 から）"
    raw = call["args"][n_vars]
    encl = enclosing_loops(loops, call["pos"])
    if not encl:
        v = js_eval(raw, env)
        return ([v], None) if v is not None else ([], raw)
    lp = encl[0]
    if not isinstance(lp["array"], list):
        return [], "%s (%s の要素が解決できない)" % (raw, lp["array_name"])
    got, unresolved = [], None
    for idx, item in enumerate(lp["array"]):
        local = dict(env)
        local[lp["param"]] = item
        if lp["index"]:
            local[lp["index"]] = float(idx)
        local = collect_vars(lp["body"], local)  # ループ内の var を毎周解く
        v = js_eval(raw, local)
        if v is None:
            unresolved = raw
        else:
            got.append(v)
    return got, unresolved


# ────────────────────────────────────────────────────────────────────────────
# プロジェクトの入力
# ────────────────────────────────────────────────────────────────────────────
_SCENE = re.compile(r"<div\b[^>]*?data-composition-src=\"([^\"]+)\"[^>]*>", re.S)


def scenes_from_index(unit: Path) -> list[dict]:
    idx = unit / "index.html"
    if not idx.exists():
        return []   # 組み立て前。build_plan が STORYBOARD の順に落ちる
    html = idx.read_text(encoding="utf-8")
    scenes = []
    for m in _SCENE.finditer(html):
        tag = m.group(0)
        start = re.search(r'data-start="([\d.]+)"', tag)
        dur = re.search(r'data-duration="([\d.]+)"', tag)
        if not (start and dur):
            continue
        scenes.append({"src": m.group(1), "start": float(start.group(1)),
                       "duration": float(dur.group(1))})
    scenes.sort(key=lambda s: s["start"])
    return scenes


def storyboard_order(unit: Path) -> list[tuple[str, str]]:
    """`STORYBOARD.md` の順に [(src, transition_in), ...] を返す。**順番が意味を持つ**
    （`index.html` が無いとき、前フレームはここで1つ前のもの）。"""
    sb = unit / "STORYBOARD.md"
    if not sb.exists():
        return []
    text = sb.read_text(encoding="utf-8")
    out: list[tuple[str, str]] = []
    for block in re.split(r"^## Frame ", text, flags=re.M)[1:]:
        src = re.search(r"^- src:\s*(\S+)", block, re.M)
        tin = re.search(r"^- transition_in:\s*(.+)$", block, re.M)
        if src:
            out.append((src.group(1).strip(), tin.group(1).strip() if tin else "?"))
    return out


def transitions_from_storyboard(unit: Path) -> dict[str, str]:
    return dict(storyboard_order(unit))


def frames_on_disk(unit: Path) -> list[Path]:
    d = unit / "compositions" / "frames"
    return sorted(d.glob("*.html")) if d.is_dir() else []


def build_plan(unit: Path) -> tuple[list[dict], bool]:
    """検査する順番を作る。戻り値は (plan, 窓が実測か)。

    `index.html` にフレームが並んでいればそれが正（窓は実測）。
    無ければ `STORYBOARD.md` の順に落ちて、窓は ASSUMED_WINDOW を仮定する。
    """
    scenes = scenes_from_index(unit)
    trans = transitions_from_storyboard(unit)
    if scenes:
        plan = []
        for i, sc in enumerate(scenes):
            window = 0.0
            if i > 0:
                prev = scenes[i - 1]
                window = round((prev["start"] + prev["duration"]) - sc["start"], 6)
            plan.append({"src": sc["src"], "window": window,
                         "declared": trans.get(sc["src"], "?"),
                         "prev": unit / scenes[i - 1]["src"] if i > 0 else None})
        return plan, True

    # ── 組み立て前。STORYBOARD の順に落ちる
    plan = []
    for i, (src, declared) in enumerate(storyboard_order(unit)):
        kind = declared.split()[0].lower() if declared != "?" else "?"
        prev_path = None
        if i > 0:
            cand = unit / storyboard_order(unit)[i - 1][0]
            prev_path = cand if cand.exists() else None
        plan.append({"src": src,
                     "window": 0.0 if kind == "cut" else ASSUMED_WINDOW,
                     "declared": declared, "prev": prev_path})
    return plan, False


# ────────────────────────────────────────────────────────────────────────────
# 検査
# ────────────────────────────────────────────────────────────────────────────
class Report:
    def __init__(self) -> None:
        self.errors: list[str] = []
        self.reviews: list[str] = []
        # **検査できなかったもの。** これがあるかぎり「問題なし」とは言わないし
        # exit も 0 にしない —— 「検査していない」と「問題が無い」は別物。
        self.blocked: list[str] = []
        self.checked = 0   # 実測の窓で検査した枚数
        self.assumed = 0   # 仮定の窓で検査した枚数

    def error(self, msg: str) -> None:
        self.errors.append(msg)

    def review(self, msg: str) -> None:
        self.reviews.append(msg)

    def block(self, msg: str) -> None:
        self.blocked.append(msg)


def check_clip_durations(path: Path, rep: Report) -> None:
    html = path.read_text(encoding="utf-8")
    root = re.search(r'data-composition-id="[^"]+"[^>]*?data-duration="([\d.]+)"', html, re.S)
    if not root:
        root = re.search(r'data-duration="([\d.]+)"', html)
        if not root:
            return
    want = root.group(1)
    found = sorted(set(re.findall(r'data-duration="([\d.]+)"', html)))
    if len(found) > 1:
        rep.error("%s: clip_duration — data-duration が揃っていない %s（ルートは %s）。"
                  "旧尺の clip は地の色すら無い白で終わる" % (path.name, found, want))


def check_script_integrity(path: Path, rep: Report) -> None:
    """`<script>` の中の `/*` と `*/` が釣り合っているか。

    ★ 2026-09-18 に**この検査ツールの作者自身が踏んだ**: 説明コメントの `/*` を
    閉じ忘れると**スクリプトの残り全部がコメントになる**。すると tween が 0 本に
    なり、**`check_crossfade` は「違反なし」を返してしまう**（通ったように見える）。
    `lint` も `check` も JS の構文を見ないので、ここで止める。
    """
    html = path.read_text(encoding="utf-8")
    if "<script>" not in html:
        return
    js = html[html.index("<script>"):html.rindex("</script>")]
    opens, closes = js.count("/*"), js.count("*/")
    if opens != closes:
        rep.error("%s: script_integrity — ブロックコメントが釣り合っていない "
                  "（`/*` %d 個 / `*/` %d 個）。**閉じ忘れるとスクリプトの残りが"
                  "丸ごとコメントになり、この検査も素通りする**" % (path.name, opens, closes))


def previous_frame_animated_props(prev_js: str) -> set[str]:
    """前フレームが動かしている（= 中立から外れうる）プロパティ名の集合。"""
    props: set[str] = set()
    js = strip_js_comments(prev_js)
    for call in collect_calls(js):
        # fromTo は from と to の両方、それ以外は vars 1つ。**前フレームが触った
        # プロパティを1つも取りこぼさない**ことがこの関数の役目。
        idxs = (1, 2) if call["method"] == "fromTo" else (1,)
        for i in idxs:
            if i < len(call["args"]):
                props.update(obj_props(call["args"][i]).keys())
    for m in re.finditer(r"gsap\s*\.\s*set\s*\(", js):
        close = match_balanced(js, js.index("(", m.end() - 1))
        if close > 0:
            args = split_args(js[js.index("(", m.end() - 1) + 1:close])
            if len(args) > 1:
                props.update(obj_props(args[1]).keys())
    return props


def t0_vars_of(call: dict, loops: list[dict], env: dict) -> dict[str, str] | None:
    """その呼び出しが **t=0 に書き込む** vars を返す（書かないなら None）。

    ・`tl.set(target, vars, 0)`            … 位置 0 なので t=0 の状態そのもの
    ・`fromTo` / `from` の `from` 引数      … immediateRender 既定 true が構築時に書く
      （`immediateRender: false` が付いていれば書かないので対象外）
    """
    positions, _ = call_positions(call, loops, env)
    if call["method"] == "set":
        if positions and all(p <= EPS for p in positions):
            return obj_props(call["args"][1])
        return None
    if call["method"] not in ("fromTo", "from"):
        return None
    vars_idx = 2 if call["method"] == "fromTo" else 1
    to_obj = obj_props(call["args"][vars_idx]) if len(call["args"]) > vars_idx else {}
    if str(to_obj.get("immediateRender", "")).strip() == "false":
        return None
    return obj_props(call["args"][1])


def check_frame(path: Path, window: float, prev_path: Path | None, rep: Report) -> list[str]:
    """窓 `window` 秒で受けるフレームを検査する。戻り値は人が読むための明細。"""
    html = path.read_text(encoding="utf-8")
    if "<script>" not in html:
        return ["  （script なし）"]
    js = strip_js_comments(html[html.index("<script>") + 8:html.rindex("</script>")])
    root_dur = re.search(r'data-duration="([\d.]+)"', html)
    env = collect_vars(js, {"DURATION": float(root_dur.group(1)) if root_dur else None})
    loops = collect_foreach(js, env)
    calls = collect_calls(js)
    prev_props = previous_frame_animated_props(
        prev_path.read_text(encoding="utf-8")) if prev_path else None

    # ── 1周目: **要素ごとに** t=0 に書き込まれるプロパティを集める
    t0_by_target: dict[str, dict[str, list[str]]] = {}
    for call in calls:
        if len(call["args"]) < 2:
            continue
        obj = t0_vars_of(call, loops, env)
        if obj is None:
            continue
        bucket = t0_by_target.setdefault(call["args"][0].strip(), {})
        for k, v in obj.items():
            bucket.setdefault(k, []).append(v)

    lines: list[str] = []
    starts: list[float] = []
    for call in calls:
        if len(call["args"]) < 2:
            continue
        positions, unresolved = call_positions(call, loops, env)
        label = call["text"][:72]
        # `tl.set` は尺 0。位置 0 なら**動きではなく t=0 の状態**なので窓の検査に掛けない。
        set_at_zero = (call["method"] == "set" and bool(positions)
                       and all(p <= EPS for p in positions))

        # ── 検査1: 窓の中で「動く」もの
        for p in positions:
            starts.append(p)
            if p < window - EPS and not (call["method"] == "set" and p <= EPS):
                kind = "位置 %.4fs の set が窓の中で跳ねる" % p if call["method"] == "set" \
                    else "開始 %.4fs は窓 %.2fs の中" % (p, window)
                rep.error("%s: transition_window — %s。"
                          "前フレームの静止画に重なって二重像になる … %s"
                          % (path.name, kind, label))
        if unresolved:
            rep.review("%s: transition_window — 開始時刻が静的に解けない `%s` … %s"
                       % (path.name, unresolved, label))

        # ── 検査2: t=0 に書き込まれる状態
        if set_at_zero:
            from_obj = obj_props(call["args"][1]) if len(call["args"]) > 1 else {}
        elif call["method"] in ("fromTo", "from"):
            vars_idx = 2 if call["method"] == "fromTo" else 1
            to_obj = obj_props(call["args"][vars_idx]) if len(call["args"]) > vars_idx else {}
            if str(to_obj.get("immediateRender", "")).strip() == "false":
                continue  # 構築時に書かない = t=0 の絵に出ない
            from_obj = obj_props(call["args"][1])
        else:
            continue
        # 可視性は**要素ごとに集めた t=0 の書き込み全部**で判定する
        # （同じ要素の opacity を別の呼び出しが 0 にしていることがある）。
        merged = t0_by_target.get(call["args"][0].strip(), {})
        hidden = target_hidden_at_t0(merged, env) or invisible_at_t0(from_obj, env)
        if hidden:
            # t=0 で見えていない = このフレームで新しく出てくる要素。
            # 前フレームの絵に重なりようがないので検査しない。
            lines.append("    t=0 hidden (%s)  %s" % (hidden, label[:44]))
            continue
        for prop, raw in from_obj.items():
            if prop in NON_STATE_KEYS:
                continue
            val = js_eval(raw, env)
            neutral = TRANSFORM_NEUTRAL.get(prop)
            shown = ("%g" % val) if val is not None else raw
            lines.append("    t=0 write  %-10s = %-10s  %s" % (prop, shown, label[:44]))
            if neutral is None:
                rep.review("%s: t0_from_state — `%s: %s` が t=0 に書かれる。"
                           "**前フレームの終端と同値か人が確かめる**（transform ではないので"
                           "中立値が決まらない） … %s" % (path.name, prop, shown, label))
                continue
            if val is None:
                rep.review("%s: t0_from_state — `%s: %s` の値が静的に解けない … %s"
                           % (path.name, prop, raw, label))
                continue
            if abs(val - neutral) < 1e-9:
                continue  # 中立 = 前フレームが何もしていなければ必ず一致する
            if prev_props is not None and prop not in prev_props:
                rep.error("%s: t0_from_state — `%s: %g` が t=0 に書かれるが、"
                          "**前フレーム（%s）は %s を1本も動かしていない = 中立 %g**。"
                          "窓の %.2f 秒ずっとずれて重なる。"
                          "t=0 の値を %g にするか、所作そのものを外す … %s"
                          % (path.name, prop, val, prev_path.name, prop, neutral,
                             window, neutral, label))
            else:
                rep.review("%s: t0_from_state — `%s: %g` が t=0 に書かれる（中立は %g）。"
                           "前フレームも %s を動かしているので、**終端の実値を人が確かめる** … %s"
                           % (path.name, prop, val, neutral, prop, label))
    if starts:
        lines.insert(0, "    開始時刻 %d 本 / 最小 %.4fs（窓 %.2fs）"
                     % (len(starts), min(starts), window))
    return lines


def check_unit(unit: Path, verbose: bool) -> Report:
    rep = Report()
    print("\n=== %s ===" % unit.name)

    on_disk = frames_on_disk(unit)
    if not on_disk:
        # フレームが1枚も無い = まだ作り始めていない。**これは「問題なし」ではない**が、
        # 指摘することも無い。STORYBOARD の予定を1枚ずつ REVIEW に並べても雑音になる。
        print("  検査対象なし — compositions/frames に .html が1枚も無い")
        return rep

    plan, measured = build_plan(unit)

    if not plan:
        if on_disk:
            # ★ ここが 2026-09-18 に見つかった穴。**フレームは在るのに検査できない。**
            # 「問題なし」と言ってはいけないし、exit 0 で通してもいけない。
            rep.block("%s: フレームが %d 枚あるのに、index.html も STORYBOARD.md も "
                      "順番を与えてくれない。**1枚も検査していない**"
                      % (unit.name, len(on_disk)))
            print("  ✗ BLOCKED — フレーム %d 枚が未検査"
                  "（index.html 未組み立て・STORYBOARD.md からも順番を取れない）"
                  % len(on_disk))
        else:
            print("  検査対象なし — フレームが1枚も無い")
        return rep

    if not measured:
        print("  ※ index.html が未組み立て。**窓は %.2fs の仮定値**で検査する"
              "（STORYBOARD.md の順・transitions inject の規約値）" % ASSUMED_WINDOW)

    for entry in plan:
        path = unit / entry["src"]
        if not path.exists():
            rep.review("%s: %s がまだ無い（未作成）" % (unit.name, entry["src"]))
            print("  [none]  %-28s まだ無い" % Path(entry["src"]).name)
            continue

        check_clip_durations(path, rep)
        check_script_integrity(path, rep)

        window, declared = entry["window"], entry["declared"]
        kind = declared.split()[0].lower() if declared != "?" else "?"

        if measured:
            # 宣言と実尺の食い違いそのものを報告する（仮定値のときは意味を持たない）
            if kind == "cut" and window > EPS:
                rep.error("%s: transition — STORYBOARD は `cut` だが index.html の尺は "
                          "%.3fs 重なっている" % (path.name, window))
            if kind not in ("cut", "?") and window <= EPS:
                rep.error("%s: transition — STORYBOARD は `%s` だが index.html に重なりが無い"
                          % (path.name, declared))

        mark = "" if measured else "（仮定）"
        tag = "%-28s 窓 %5.3fs%s  transition_in: %s" % (path.name, window, mark, declared)
        if window <= EPS:
            print("  [skip] " + tag)
            continue
        if kind not in ("crossfade", "?"):
            # push-slide などは2枚が並んで平行移動する。前の絵に重ならないので 8g の対象外。
            print("  [info]  " + tag + "  — 8g の対象外（2枚が重ならない）")
            continue
        if kind == "?":
            rep.review("%s: transition — STORYBOARD から transition_in を読めなかった。"
                       "%.3fs の窓があるので**安全側に倒して検査した**。"
                       "`crossfade` でなければこの指摘は当たらない" % (path.name, window))
        if entry["prev"] is None:
            rep.review("%s: t0_from_state — **前フレームがまだ無い**ので t=0 の状態を"
                       "突き合わせられない。組み上がってからもう一度回すこと" % path.name)

        print("  [check] " + tag)
        if measured:
            rep.checked += 1
        else:
            rep.assumed += 1
        detail = check_frame(path, window, entry["prev"], rep)
        if verbose:
            for line in detail:
                print(line)
        elif detail:
            print("  " + detail[0].strip())

    # フレームは在る・窓のあるものが1枚も無かった → 検査していないのと同じ
    if on_disk and rep.checked + rep.assumed == 0 and not rep.errors:
        rep.block("%s: フレームが %d 枚あるが、**crossfade で受ける枚が1枚も無かった**。"
                  "STORYBOARD.md の transition_in を確かめること" % (unit.name, len(on_disk)))
    return rep


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("units", nargs="+", help="ユニットのディレクトリ（複数可）")
    ap.add_argument("--strict", action="store_true", help="REVIEW があっても 1 を返す")
    ap.add_argument("-v", "--verbose", action="store_true", help="t=0 に書かれる値を全部出す")
    args = ap.parse_args()

    errors: list[str] = []
    reviews: list[str] = []
    blocked: list[str] = []
    checked = assumed = 0
    for raw in args.units:
        unit = Path(raw)
        if not unit.is_dir():
            continue
        rep = check_unit(unit, args.verbose)
        errors += rep.errors
        reviews += rep.reviews
        blocked += rep.blocked
        checked += rep.checked
        assumed += rep.assumed

    if blocked:
        print("\n" + "─" * 78)
        print("BLOCKED — **検査できていない**（%d 件）" % len(blocked))
        for b in blocked:
            print("  ✗ " + b)
    if errors:
        print("\n" + "─" * 78)
        print("ERROR — 直す（%d 件）" % len(errors))
        for e in errors:
            print("  ✗ " + e)
    if reviews:
        print("\n" + "─" * 78)
        print("REVIEW — 静的には解けない。**人が見る**（%d 件）" % len(reviews))
        for r in reviews:
            print("  ? " + r)

    # ★ 件数を必ず言う。「検査していない」を「問題なし」と読ませないため。
    print("\n検査したフレーム %d 枚（実測の窓 %d / 仮定の窓 %d）" % (checked + assumed, checked, assumed))
    if blocked or errors or reviews:
        print("BLOCKED %d / ERROR %d / REVIEW %d" % (len(blocked), len(errors), len(reviews)))
    elif checked + assumed:
        print("問題なし。")
    else:
        print("検査対象が無かった（問題が無いという意味ではない）。")
    return 1 if (blocked or errors or (args.strict and reviews)) else 0


if __name__ == "__main__":
    raise SystemExit(main())
