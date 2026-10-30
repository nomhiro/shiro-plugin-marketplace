"""slide_kit.py — 「スライド型」のフレームを作る部品（2026-09-21・パイロット）。

型の規則はプラグインの `references/slide-format.md`。ここはその実装で、次を**コードで強制**する:

  * タイトルは常設（`Slide(title=...)` が必須。空にできない）
  * 動きは2種類だけ（2026-09-21 ユーザー決定）:
      ① 不透明度 0→1 のフェード（`reveal`。FADE 秒）
      ② 矢印の描画（`arrow`。線が伸びてから、その先の要素がフェードで現れる）
    移動・拡大・回転・連続変化は書けない
  * リビールは語の語末に着地する（`at` = 語末の秒。フェードは `at - FADE` から）
  * 1枚のリビールは MAX_REVEALS 回まで（超えたら例外）
  * 切り替えは STORYBOARD の `transition_in`（cut か `crossfade 0.2s`）。フレーム側は、
    切り替えの窓（先頭 XFADE 秒）で何も動かさない（規則 8g）＝最初の動きの開始が XFADE 以降であることを検査する

文字幅は同梱の BIZ UDPGothic を fontTools で実測して収まりを検査する
（`measure` の「字数 × em」はカナで外れる — CLAUDE.md 参照）。
"""
from __future__ import annotations

import re
from contextlib import contextmanager
from pathlib import Path

from fontTools.ttLib import TTFont

W, H = 1920, 1080
CQW = 19.2                 # 1cqw = 19.2px @1920
FADE = 0.4                 # リビールの長さ（s）。これより長くしない
DRAW = 0.5                 # 矢印の描画の長さ（s）
HEAD = 0.1                 # 矢じりのフェード（s。線が伸び切る直前）
XFADE = 0.5                # 切り替えのクロスフェード（s）。この窓では何も動かさない（2026-09-22: 0.2 → 0.5。「速すぎる」への対処）
MAX_REVEALS = 6            # 1枚あたりのリビール上限。通常は 2〜4。列挙（手法名・アジェンダ）を1項目ずつ出す枚だけ 5〜6
EM_CENTER = 0.38           # BIZ UDPGothic: 文字箱の中心は baseline の 0.38em 上（asc 0.8799 − 0.5）

# ★ 配色は `frame.md` の `colors:` が Source of Truth。ここに値を手で写さない（二重管理になる）。
# slide_kit 内の名前 → frame.md のキー
_FRAME_KEYS = {
    "paper": "paper", "ink": "ink", "mute": "ink-mute", "rule": "frame-rule", "face": "frame-face",
    "subj": "subject", "subj-face": "subject-face", "acc": "accent", "acc-face": "accent-face",
}


def load_palette(frame_md: Path) -> dict[str, str]:
    """`frame.md` の front matter のうち `colors:` の節だけを読む。足りないキーは例外。"""
    lines = frame_md.read_text(encoding="utf-8").splitlines()
    cols: dict[str, str] = {}
    inside = False
    for line in lines:
        if line.startswith("colors:"):
            inside = True
            continue
        if inside and line and not line.startswith(" "):
            break                                   # 次の最上位キー（radius: など）で終わり
        m = re.match(r'\s{2}([a-z0-9-]+):\s*"([^"]+)"', line) if inside else None
        if m:
            cols[m.group(1)] = m.group(2)
    missing = [v for v in _FRAME_KEYS.values() if v not in cols]
    if missing:
        raise KeyError(f"{frame_md}: colors: に {missing} が無い")
    return {k: cols[v] for k, v in _FRAME_KEYS.items()}


def load_durations(unit_dir: Path) -> dict[int, float]:
    """STORYBOARD.md（sync-durations 済み）の `- duration:` をフレーム番号で返す。秒数を手書きしない。"""
    sb = (Path(unit_dir) / "STORYBOARD.md").read_text(encoding="utf-8")
    return {int(m.group(1)): float(m.group(2))
            for m in re.finditer(r"^## Frame (\d+).*?^- duration: ([\d.]+)s", sb, re.S | re.M)}


class Beats:
    """`_beats.md`（make_beats.py ＝ 実測 STT）から語末を引く。**手で書かない。**
    時刻は行頭の無音（audio_meta の head_s）を含む、フレーム先頭からの時刻。"""

    def __init__(self, unit_dir: Path):
        txt = (Path(unit_dir) / ".hyperframes" / "frame-packets" / "_beats.md").read_text(encoding="utf-8")
        fence = "`" * 3
        self.tok: dict[int, list[tuple[str, float]]] = {}
        pattern = r"## Frame (\d+) — [\d.]+s.*?" + fence + r"\n(.*?)" + fence
        for m in re.finditer(pattern, txt, re.S):
            toks = []
            for line in m.group(2).splitlines():
                mm = re.match(r"\s*([\d.]+)s 〜\s*([\d.]+)s\s+(.*)", line)
                if mm:
                    toks.append((mm.group(3), float(mm.group(2))))
            self.tok[int(m.group(1))] = toks

    def __call__(self, frame: int, phrase: str, nth: int = 0) -> float:
        """連続する語（STT の綴りのまま）を連結して `phrase` になる箇所の**最後の語の終了時刻**。
        見つからなければ例外（STT の綴りが変わったら気づける）。"""
        toks = self.tok[frame]
        hit = 0
        for i in range(len(toks)):
            acc, j = "", i
            while j < len(toks) and len(acc) < len(phrase):
                acc += toks[j][0]
                j += 1
            if acc == phrase:
                if hit == nth:
                    return toks[j - 1][1]
                hit += 1
        raise KeyError(f"frame {frame}: 「{phrase}」（{nth} 番目）が _beats.md に無い。語: {' '.join(t for t, _ in toks)}")


class Fonts:
    def __init__(self, font_dir: Path):
        self._f = {}
        for wgt in (400, 700):
            ft = TTFont(font_dir / f"biz-udpgothic-japanese-{wgt}-normal.woff2")
            self._f[wgt] = (ft.getBestCmap(), ft["hmtx"], ft["head"].unitsPerEm)

    def width(self, text: str, size_cqw: float, weight: int = 400) -> float:
        cmap, hm, upem = self._f[weight]
        px = size_cqw * CQW
        total = 0.0
        for ch in text:
            g = cmap.get(ord(ch))
            total += (hm[g][0] / upem) if g else 1.0
        return total * px


class Slide:
    def __init__(self, unit_dir: Path, frame_id: str, duration: float, title: str,
                 tag: tuple[str, int, int] | None = None, compact: bool = False):
        if not title.strip():
            raise ValueError("スライド型: タイトルは常設。空にできない")
        self.unit = Path(unit_dir)
        self.id = frame_id                       # 例 "03-bootstrap"
        self.p = "f" + frame_id.split("-")[0]    # 例 "f03"（id・class の接頭辞）
        self.duration = duration
        self.fonts = Fonts(self.unit / "assets" / "fonts")
        self.palette = load_palette(self.unit / "frame.md")
        self.parts: list[str] = []
        self.beats: list[tuple[str, float, str]] = []   # (group id, 着地, 注記)
        self.draws: list[tuple[str, str, float]] = []    # (線の id, 矢じりの id, 描画の開始)
        self._cur: tuple[str, float] | None = None       # いまのリビール (gid, at)
        self._pending: list[str] = []                    # リビールの外に出す矢印のSVG
        self._n_arrow = 0
        self._static = False                             # past() の中（前の行の図を静止で描く）
        if compact:
            self._title_compact(title)
        else:
            self._title(title)
        if tag:
            self._tag(*tag)

    # ── クラス名 ────────────────────────────────────────────────────────
    def c(self, *names: str) -> str:
        return " ".join(f"{self.p}-{n}" for n in names)

    def add(self, s: str) -> None:
        self.parts.append(s)

    # ── リビール（唯一の動き）──────────────────────────────────────────
    @contextmanager
    def past(self):
        """ページ（2026-10-08・ユーザー指示「スライドの移り変わりが多すぎる。1枚の情報量を多く」）。
        語りの数行（フレーム）を1枚として続けて見せるとき、**前の行で出た図を、着地した姿のまま最初から描く**。
        この中の `reveal` は動きを作らない（群も beats も作らず、中身をそのまま描く）。矢印も静止で描く。
        同じページの次のフレームは STORYBOARD で `transition_in: cut`（前の枚の終わりと同じ絵から始まるので継ぎ目が見えない）。"""
        prev, self._static = self._static, True
        try:
            yield
        finally:
            self._static = prev

    @contextmanager
    def reveal(self, name: str, at: float, note: str = ""):
        if self._static:
            yield
            return
        lim = getattr(self, "max_reveals", MAX_REVEALS)   # 2026-10-19: 長い枚（約50秒）だけ slides.py で s.max_reveals = 7 を許す（理由を書く）
        if len(self.beats) >= lim:
            raise ValueError(f"{self.id}: リビールは {lim} 回まで（{name} が超過）")
        if at > self.duration:
            raise ValueError(f"{self.id}: {name} の着地 {at}s が尺 {self.duration}s を超える")
        gid = f"{self.p}-{name}"
        if at - FADE < XFADE:
            raise ValueError(f"{self.id}: {name} のフェード開始 {at - FADE:.2f}s が切り替えの窓（{XFADE}s）に入る")
        if self.beats and at < max(b[1] for b in self.beats) - 0.05:
            # 2026-10-12: E() の出現回の取り違え（語の最初の出現を引いて、あとの行が先に出る）を早く拾う。例外にはしない（意図した順序もある）
            import sys as _sys
            print(f"WARN {self.id}: {name} の着地 {at:.1f}s が直前までの reveal（{max(b[1] for b in self.beats):.1f}s）より早い（E() の出現回の取り違えの疑い。意図した順序なら無視）", file=_sys.stderr)
        self.beats.append((gid, at, note))
        self._cur = (gid, at)
        self._pending = []
        self.add(f'<g id="{gid}">')
        yield
        self.add("</g>")
        # 矢印はフェードする群の外に置く（群が不透明度 0 の間も線を描くため）
        for part in self._pending:
            self.add(part)
        self._cur, self._pending = None, []

    # ── 部品 ────────────────────────────────────────────────────────────
    def rect(self, x, y, w, h, cls="box", r=12):
        self.add(f'<rect class="{self.c(cls)}" x="{x:.2f}" y="{y:.2f}" width="{w:.2f}" height="{h:.2f}" rx="{r}"/>')

    def line(self, x1, y1, x2, y2, cls="rule"):
        self.add(f'<line class="{self.c(cls)}" x1="{x1:.2f}" y1="{y1:.2f}" x2="{x2:.2f}" y2="{y2:.2f}"/>')

    def dot(self, x, y, r, cls="dot"):
        self.add(f'<circle class="{self.c(cls)}" cx="{x:.2f}" cy="{y:.2f}" r="{r}"/>')

    def text(self, x, cy, s, size, color="ink", anchor="middle", bold=False, fit=None, overlap=False):
        """cy は文字箱の縦中心。fit=(最大幅) を渡すと収まりを検査する。
        overlap=True は**意図した重ね**（教材ページで薄い行の上に強調の行を重ねる、など）。
        `data-layout-allow-overlap` を**その要素自身に**付ける（祖先に付けても効かない。CLAUDE.md 8e）。"""
        wgt = 700 if bold else 400
        w = self.fonts.width(s, size, wgt)
        if fit is not None and w > fit:
            raise ValueError(f"{self.id}: 「{s}」{size}cqw の幅 {w:.0f}px が枠 {fit:.0f}px を超える")
        base = cy + EM_CENTER * size * CQW
        cls = self.c(color, "b") if bold else self.c(color)
        allow = ' data-layout-allow-overlap=""' if overlap else ""
        self.add(f'<text class="{cls}" x="{x:.2f}" y="{base:.2f}" text-anchor="{anchor}" '
                 f'style="font-size:{size}cqw"{allow}>{s}</text>')
        return w

    def arrow(self, x1, y1, x2, y2, head=24, cls="rule-b", lead=True):
        """矢印。リビールの中では「描画」になる（外に出て、線が伸びてから矢じりが現れる）。
        lead=True : 先の要素（群のフェード）より先に描く。「ここへ向かう」矢印
        lead=False: 群のフェードと同時に描く。群の中の要素から出る矢印
        リビールの外（始めから見えている枚）では静止した矢印になる。"""
        import math
        dx, dy = x2 - x1, y2 - y1
        L = math.hypot(dx, dy)
        ux, uy = dx / L, dy / L
        bx, by = x2 - ux * head, y2 - uy * head
        hw = head * 0.62
        px, py = -uy, ux
        pts = f"{x2:.2f},{y2:.2f} {bx + px * hw:.2f},{by + py * hw:.2f} {bx - px * hw:.2f},{by - py * hw:.2f}"
        if self._cur is None:
            self.add(f'<line class="{self.c(cls)}" x1="{x1:.2f}" y1="{y1:.2f}" x2="{bx:.2f}" y2="{by:.2f}"/>')
            self.add(f'<polygon class="{self.c("head")}" points="{pts}"/>')
            return
        gid, at = self._cur
        self._n_arrow += 1
        lid, hid = f"{gid}-line{self._n_arrow}", f"{gid}-head{self._n_arrow}"
        start = at - FADE - DRAW if lead else at - DRAW
        if start < XFADE:
            raise ValueError(f"{self.id}: {gid} の矢印の描画開始 {start:.2f}s が切り替えの窓（{XFADE}s）に入る")
        self.draws.append((lid, hid, start))
        self._pending.append(
            f'<path id="{lid}" class="{self.c(cls, "draw")}" pathLength="1" '
            f'd="M{x1:.2f} {y1:.2f} L{bx:.2f} {by:.2f}"/>')
        self._pending.append(f'<polygon id="{hid}" class="{self.c("head")}" points="{pts}"/>')

    def image(self, x, y, w, h, href, frame=True):
        """画面のキャプチャ（2026-10-18 ユーザー指示「実際の画面のキャプチャを載せてほしい」）。
        href は `assets/captures/<名前>.png`（ユニットの中に置く。切り出しは事前に PIL で行い、ここでは拡大縮小だけ）。
        縦横比は保つ（meet）。frame=True で細い枠を付ける。"""
        if not (self.unit / href).is_file():
            raise ValueError(f"{self.id}: キャプチャ {href} がユニットに無い")
        self.add(f'<image href="{href}" x="{x:.2f}" y="{y:.2f}" width="{w:.2f}" height="{h:.2f}" preserveAspectRatio="xMidYMid meet"/>')
        if frame:
            self.add(f'<rect class="{self.c("shot")}" x="{x:.2f}" y="{y:.2f}" width="{w:.2f}" height="{h:.2f}" rx="4"/>')

    def highlight(self, x, y, w, h):
        """キャプチャの上の強調の枠（青・太線）。一度に1つだけ出す（record-practice-screen の作法）。"""
        self.add(f'<rect class="{self.c("hl")}" x="{x:.2f}" y="{y:.2f}" width="{w:.2f}" height="{h:.2f}" rx="8"/>')

    def plus(self, cx, cy, size=34):
        h = size / 2
        self.line(cx - h, cy, cx + h, cy, "rule-b")
        self.line(cx, cy - h, cx, cy + h, "rule-b")

    def cross(self, cx, cy, size=30, cls="x-acc"):
        h = size / 2
        self.line(cx - h, cy - h, cx + h, cy + h, cls)
        self.line(cx - h, cy + h, cx + h, cy - h, cls)

    def check(self, cx, cy, size=34, cls="ok-subj"):
        h = size / 2
        self.add(f'<polyline class="{self.c(cls)}" points="{cx - h:.2f},{cy:.2f} {cx - h * 0.25:.2f},{cy + h * 0.75:.2f} {cx + h:.2f},{cy - h * 0.7:.2f}"/>')

    def chip(self, x, y, w, h, s, size, cls="box", color="ink", bold=True):
        self.rect(x, y, w, h, cls)
        self.text(x + w / 2, y + h / 2, s, size, color, bold=bold, fit=w - 48)

    def tree(self, x, y, w, h, leaf="leaf", node="node"):
        """決定木の縮図（根1・中間2・葉4）。3-1-5 の木と同じ形。"""
        n = min(w * 0.19, h * 0.21)
        r = n * 0.22
        root = (x + w / 2, y + n / 2)
        mids = [(x + w * 0.25, y + h / 2), (x + w * 0.75, y + h / 2)]
        leaves = [(x + w * (2 * i + 1) / 8, y + h - n / 2) for i in range(4)]
        for m in mids:
            self.line(root[0], root[1] + n / 2, m[0], m[1] - n / 2)
        for i, lf in enumerate(leaves):
            m = mids[i // 2]
            self.line(m[0], m[1] + n / 2, lf[0], lf[1] - n / 2)
        for (cx, cy) in [root] + mids:
            self.rect(cx - n / 2, cy - n / 2, n, n, node, r)
        for (cx, cy) in leaves:
            self.rect(cx - n / 2, cy - n / 2, n, n, leaf, r)

    # ── タイトルと進行札（常設）───────────────────────────────────────
    def _title(self, title: str):
        self.rect(40, 52, 14, 96, "marker", 7)
        w = self.text(92, 100, title, 5.0, "ink", "start", bold=True, fit=1780)
        self.title_w = w

    # 2026-10-21 ユーザー指示「ハンズオンの動画、タイトル部分はもっと狭くていい。VSCodeとかハンズオン部分をもっと画面全体になるようにした方が見やすい。」
    # 実践の本体（画面を全幅で見せる枚）は、タイトルを上端の細い帯（高さ COMPACT_BAND）に小さく置く
    COMPACT_BAND = 64

    def _title_compact(self, title: str):
        self.rect(28, 12, 10, 40, "marker", 5)
        w = self.text(56, 32, title, 2.3, "ink", "start", bold=True, fit=1820)
        self.title_w = w

    def _tag(self, label: str, cur: int, total: int):
        """右上の進行札。[ 並列 ] ■□□ — 数字を使わず、どこまで進んだかを示す。"""
        sq, gap = 34, 14
        sx_end = 1880
        sx0 = sx_end - (total * sq + (total - 1) * gap)
        for i in range(total):
            x = sx0 + i * (sq + gap)
            self.rect(x, 100 - sq / 2, sq, sq, "pip-on" if i == cur - 1 else "pip", 8)
        tw = self.fonts.width(label, 3.2, 700)
        pw = tw + 64
        px = sx0 - 28 - pw
        if 92 + self.title_w + 40 > px:
            raise ValueError(f"{self.id}: タイトル（右端 {92 + self.title_w:.0f}px）が進行札（左端 {px:.0f}px）に近すぎる")
        self.rect(px, 60, pw, 80, "pill", 40)
        self.text(px + pw / 2, 100, label, 3.2, "wht", bold=True)

    # ── 出力 ────────────────────────────────────────────────────────────
    def html(self, ident: str | None = None) -> str:
        p, D = self.p, f"{self.duration:g}"
        css = CSS_TEMPLATE.replace("§", p)
        css = css.replace("/*PALETTE*/", "\n".join(f"      --{k}: {v};" for k, v in self.palette.items()))
        # 時刻は直値で展開する（配列＋forEach だと check_crossfade.py が静的に解けず REVIEW が増える）
        stmts = []
        for gid, at, note in self.beats:
            stmts.append(f'tl.fromTo("#{gid}", {{ opacity: 0 }}, {{ opacity: 1, duration: {FADE}, ease: "power1.out" }}, {at - FADE:.3f});'
                         + (f"   // {note}（着地 {at:g}s）" if note else ""))
        for lid, hid, start in self.draws:
            stmts.append(f'tl.fromTo("#{lid}", {{ strokeDashoffset: 1 }}, {{ strokeDashoffset: 0, duration: {DRAW}, ease: "power1.inOut" }}, {start:.3f});')
            stmts.append(f'tl.fromTo("#{hid}", {{ opacity: 0 }}, {{ opacity: 1, duration: {HEAD}, ease: "none" }}, {start + DRAW - HEAD:.3f});')
        tweens_js = ("\n      ".join(stmts)) if stmts else "/* 動きは無い（無音の静止フレーム） */"
        rid = ident or self.id
        svg = "\n      ".join(self.parts)
        return f'''<template>
  <style>
    /* {self.id} — スライド型（型の規則は references/slide-format.md）。
       動きは「リビール＝不透明度のフェード」だけ。着地は語の語末（_beats.md）。
       ★ この HTML は slide_kit.py が生成する。直すときは生成元（slides.py）を直す。 */
    @font-face {{
      font-family: "BIZ UDPGothic";
      src: url("assets/fonts/biz-udpgothic-japanese-400-normal.woff2") format("woff2");
      font-weight: 400;
      font-display: block;
    }}
    @font-face {{
      font-family: "BIZ UDPGothic";
      src: url("assets/fonts/biz-udpgothic-japanese-700-normal.woff2") format("woff2");
      font-weight: 700;
      font-display: block;
    }}
{css}
  </style>
  <div id="root" data-composition-id="{rid}" data-start="0" data-duration="{D}" data-width="{W}" data-height="{H}">
    <div id="{p}-ground" class="clip {p}-ground" data-start="0" data-duration="{D}" data-track-index="0"></div>
    <svg class="{p}-svg" viewBox="0 0 {W} {H}" preserveAspectRatio="none" xmlns="http://www.w3.org/2000/svg">
      {svg}
    </svg>
  </div>
  <script>
    (function () {{
      /* 動きは「フェード」と「矢印の描画」だけ。着地（s）は語の語末（フェードは着地 − FADE から）。 */
      var tl = gsap.timeline({{ paused: true }});
      {tweens_js}
      window.__timelines = window.__timelines || {{}};
      window.__timelines["{rid}"] = tl;
    }})();
  </script>
</template>
'''


# ── 教材ページの部品（2026-10-08・ユーザー指示「別の講座みたいに教材感を。解説文章もつける」）────────
# 3-1-1 で作って全ユニット共通にした。型は references/slide-format.md §2・§2b。

TOP_Y = 240        # タイトル直下のテキスト行の縦中心（タイトルの文字の下端 約148 から約40px 空ける）
TOP_SIZE = 5.0


LEAD_Y = 228       # 解説文の縦中心（タイトルの文字の下端 約148 の下）
LEAD_SIZE = 3.2    # タイトル（5.0cqw・太字）より小さく、太字にしない


def lead(s: "Slide", text: str, size: float = LEAD_SIZE, y: float = LEAD_Y):
    """タイトル直下の**解説文**（2026-10-08・ユーザー指示「タイトルの下の文章は、タイトルより少し小さくして
    解説文章であるべき。最初から表示しておいていい」）。**最初から表示する（リビールしない）**。
    1行に収める（28字前後まで）。語りの丸写しではなく、その枚の内容を一文で説明する。"""
    s.text(92, y, text, size, "ink", "start", bold=False, fit=1788)


def top_row(s: "Slide", items, size: float = TOP_SIZE, y: float = TOP_Y):
    """★ 2026-10-08 から**タイトル直下は `lead()`（解説文・最初から表示）を使う**。これは旧方式（語ごとにリビールする札）。
    名前・説明は**箱にせず、図の上（タイトル直下）にテキストで置く**（「下の箱は図解というより説明」）。
    **箱は図（対象・器）だけ**に使う。items = [(キー, 文字, 色, 語末, 注記)]。
    左揃え（タイトルと同じ x=92）で語の順に左から並べる。位置は全項目の幅から先に決める（あとの語で前の語が動かない）。"""
    gap = 90
    xs, x = [], 92
    for _key, text, _col, _at, _note in items:
        xs.append(x)
        x += s.fonts.width(text, size, 700) + gap
    if x - gap > 1880:
        raise ValueError(f"{s.id}: タイトル直下のテキストが右端 1880px を超える（{x - gap:.0f}px）")
    for (key, text, col, at, note), x in zip(items, xs):
        with s.reveal(key, at, note):
            s.text(x, y, text, size, col, "start", bold=True)


@contextmanager
def _maybe_reveal(s: "Slide", name, at, note):
    if at is None:
        yield
    else:
        with s.reveal(name, at, note):
            yield


def lesson_rows(s: "Slide", rows, check: bool = False, y0: float = 380, y1: float = 950, gap: float = 30, split: float = 720,
                show_at: float | None = None):
    """教材ページの行。行は**始めから薄い色で全部見えている**（地図）。語りがその行に来たら、
    行が青い面＋濃い文字で**強調**される（強調は残る＝進み具合が見える）。check=True で行に ✓（要点の枚）。
    rows = [(キー, 名前, 解説文, 語末)]。解説文は**その枚の語りで読む語だけ**で書く（規則8）。
    行の高さは (y1 − y0 − 隙間) を行数で割る（上限 170）。既定値は3行で 380/580/780（3-1-1 と同じ）。
    split は解説文の開始 x（名前の欄の幅）。長い名前（ロジスティック回帰 など）は大きくする。
    show_at: ページの途中（cut で入るフレーム）に置くときは、薄い行も語末（例「3つです」）でフェードさせる。"""
    n = len(rows)
    h = min(170.0, (y1 - y0 - (n - 1) * gap) / n)
    ys = [y0 + i * (h + gap) for i in range(n)]
    ns, es = (4.6, 4.0) if h >= 160 else (4.2, 3.8)
    with _maybe_reveal(s, "rows", show_at, "薄い行（地図）を出す"):
        for y, (_k, name, explain, _at) in zip(ys, rows):          # 始めから見えている: 薄い行
            s.rect(40, y, 1840, h, "box")
            s.text(110, y + h / 2, name, ns, "mute", "start", bold=True, fit=split - 160, overlap=True)
            s.text(split, y + h / 2, explain, es, "mute", "start", fit=1840 - split - 100, overlap=True)   # 右端の ✓ の分を空ける
    for y, (key, name, explain, at) in zip(ys, rows):
        with s.reveal(key, at, f"「{name}」の行"):
            s.rect(40, y, 1840, h, "box-subj")
            s.text(110, y + h / 2, name, ns, "subj", "start", bold=True, fit=split - 160, overlap=True)   # 薄い行の上に重ねる（意図した重ね）
            s.text(split, y + h / 2, explain, es, "ink", "start", fit=1840 - split - 100, overlap=True)
            if check:
                s.check(1810, y + h / 2, 44)


# ── ページ（2026-10-08・ユーザー指示「スライドの移り変わりが多すぎる。1枚の情報量を多く」）──────────
# 語りの1行＝1フレーム（音声・字幕の単位）は変えず、**関連する数行を1枚（ページ）として続けて見せる**。
# ページの中では、前の行の図は着地した姿で最初から見えていて、その行の図だけが語りに合わせて足される。
# 切り替えは、ページの先頭だけ crossfade、ページの中は cut（前の枚の終わりと同じ絵から始まるので見えない）。

def render_pages(unit: Path, D: dict, pages, out: Path, lead_fn=None, compact: bool = False):
    """pages = [(タイトル, 解説文 or None, [(フレーム番号, id, 描く関数(s)), ...]), ...]
    描く関数は `s.reveal` で語末に合わせて足す。同じページの後のフレームでは `s.past()` の中で呼ばれ、静止で描かれる。
    STORYBOARD.md の voiceover（SCRIPT.md から）・scene・transition_in もここで合わせる（手で直さない）。"""
    out.mkdir(parents=True, exist_ok=True)
    plan = {}
    for pi, (title, lead_text, frames) in enumerate(pages):
        for k, (n, fid, fn) in enumerate(frames):
            s = Slide(unit, fid, D[n], title, compact=compact)
            if lead_text:
                (lead_fn or lead)(s, lead_text)
            with s.past():
                for _n, _fid, prev in frames[:k]:
                    prev(s)
            fn(s)
            (out / f"{s.id}.html").write_text(s.html(), encoding="utf-8", newline="\n")
            first = (pi == 0 and k == 0)
            tr = "cut" if (first or k > 0) else "crossfade 0.5s"
            plan[n] = (title, tr)
            print(f"  p{pi + 1} {s.id}.html  reveals={len(s.beats)}  D={s.duration:g}s  in={tr}")
    _sync_storyboard(unit, plan)


def _sync_storyboard(unit: Path, plan: dict):
    import sys as _sys
    _sys.path.insert(0, str(Path(__file__).resolve().parent))
    from tts import spoken_by_frame
    spoken = spoken_by_frame(Path(unit) / "SCRIPT.md")
    p = Path(unit) / "STORYBOARD.md"
    raw = p.read_bytes()
    crlf = b"\r\n" in raw
    sb = raw.decode("utf-8").replace("\r\n", "\n")
    blocks = re.split(r"(?m)^(?=## Frame \d+ — )", sb)
    for i, b in enumerate(blocks):
        m = re.match(r"## Frame (\d+) — ", b)
        if not m or int(m.group(1)) not in plan:
            continue
        n = int(m.group(1))
        title, tr = plan[n]
        b = re.sub(r"(?m)^## Frame \d+ — .*$", f"## Frame {n} — {title}", b, count=1)
        b = re.sub(r"(?m)^- scene: .*$", f"- scene: {title}", b, count=1)
        b = re.sub(r"(?m)^- transition_in: .*$", f"- transition_in: {tr}", b, count=1)
        if n in spoken:
            vo = spoken[n].replace('"', "”")
            b = re.sub(r'(?m)^- voiceover: .*$', lambda _m: f'- voiceover: "{vo}"', b, count=1)
        blocks[i] = b
    sb = "".join(blocks)
    p.write_bytes((sb.replace("\n", "\r\n") if crlf else sb).encode("utf-8"))


# ── レクチャーの流れ（冒頭・区切りで共通。2026-10-08 受講者目線レビューで型をそろえた）──────────
# 縦1列で上から読む（2列×3段は読む順が決まらなかった）。名前は**全部最初から表示**する
# （ユーザー承認 2026-10-08「全体のどこにいるか分かるほうがよい」。冒頭の流れで全部を一度読んでいる）。
AGENDA_Y0, AGENDA_Y1, AGENDA_GAP = 290, 1030, 12


def _agenda_ys(n: int):
    h = (AGENDA_Y1 - AGENDA_Y0 - (n - 1) * AGENDA_GAP) / n
    return [AGENDA_Y0 + i * (h + AGENDA_GAP) for i in range(n)], h


def _agenda_row(s: "Slide", y, h, name, state):
    """state: "done"（済み：薄い文字＋✓）／"now"（いま：青い面＋青い太字）／"todo"（これから：濃い文字）
    面は半透明なので、まず白い面を敷く（重ねたときに下の文字が透けて二重に見えた。2026-10-08）。"""
    size = 4.0
    s.rect(32, y - 5, 1856, h + 10, "wht", 14)   # 下の行の太い縁（いま）がはみ出して残らないよう、少し広く白で覆う（再レビュー[低]）
    s.rect(40, y, 1840, h, "box-white")
    if state == "now":
        s.rect(40, y, 1840, h, "box-subj")
        s.text(110, y + h / 2, name, size, "subj", "start", bold=True, fit=1600, overlap=True)
    else:
        s.rect(40, y, 1840, h, "box")
        s.text(110, y + h / 2, name, size, "mute" if state == "done" else "ink", "start", bold=(state != "done"), fit=1600, overlap=True)
        if state == "done":
            s.check(1810, y + h / 2, 40)


def agenda_rows(s: "Slide", names, now_at=None):
    """冒頭の「このレクチャーの流れ」。全部の名前を「これから」で出し、now_at（語末）で1行目を「いま」にする。"""
    ys, h = _agenda_ys(len(names))
    for y, name in zip(ys, names):
        _agenda_row(s, y, h, name, "todo")
    if now_at is not None:
        with s.reveal("now", now_at, "1行目を「いま」にする"):
            _agenda_row(s, ys[0], h, names[0], "now")


def bridge_rows(s: "Slide", names, nxt: int, at_prev: float, at_next: float):
    """区切りの札。nxt＝次に始まるユニットの番号（1始まり、2以上）。
    始め: 済み（✓）・直前（いま）・これから。「ここまで」の語末で直前を済みに、「次は」の語末で次を「いま」にする。"""
    ys, h = _agenda_ys(len(names))
    for i, (y, name) in enumerate(zip(ys, names), 1):
        _agenda_row(s, y, h, name, "done" if i < nxt - 1 else ("now" if i == nxt - 1 else "todo"))
    with s.reveal("prev", at_prev, "「ここまで」の名前の語末（直前を済みに）"):
        _agenda_row(s, ys[nxt - 2], h, names[nxt - 2], "done")
    with s.reveal("next", at_next, "「次は」の名前の語末（次を「いま」に）"):
        _agenda_row(s, ys[nxt - 1], h, names[nxt - 1], "now")


# ── 現在地（2026-10-09・ユーザー指示「セクション全体のうち何についてのレクチャーか、進捗が分かることが大事」）──────
# 1ユニット＝1レクチャー。各レクチャーの頭に、章の中のどこかを2段の地図で見せる。
# 左＝章のまとまり（いまのまとまりが青）、右＝いまのまとまりの中身（済み ✓・いま 青・これから 濃い文字）。
# 章の全部（22ユニット）を1枚に並べると読めないので2段にする。

def _row_size(s: "Slide", name: str, w, h, size: float) -> float:
    """行の高さ・幅に収まる大きさに縮める（まとまりが多い章＝第5・6・10章用。下限 1.45cqw）。
    高さは文字の高さ×1.5 まで、幅は fit（w−130）に収まるまで 0.05 刻みで縮める。"""
    size = min(size, round((h / 1.5) / 19.2, 2))
    while size > 1.45 and s.fonts.width(name, size, 700) > w - 130:
        size = round(size - 0.05, 2)
    return max(size, 1.45)


def _row(s: "Slide", x, y, w, h, name, state, size):
    size = _row_size(s, name, w, h, size)
    s.rect(x - 6, y - 5, w + 12, h + 10, "wht", 14)
    s.rect(x, y, w, h, "box-white")
    if state == "now":
        s.rect(x, y, w, h, "box-subj")
        s.text(x + 50, y + h / 2, name, size, "subj", "start", bold=True, fit=w - 130, overlap=True)
    else:
        s.rect(x, y, w, h, "box")
        s.text(x + 50, y + h / 2, name, size, "mute" if state == "done" else "ink", "start",
               bold=(state != "done"), fit=w - 130, overlap=True)
        if state == "done":
            s.check(x + w - 50, y + h / 2, 36)


def position_map(s: "Slide", groups, gi: int, units, ui: int, at_group: float, at_unit: float):
    """groups = 章のまとまりの名前、gi = いまのまとまり（0始まり）。units = いまのまとまりのユニット名、ui = いまのユニット（0始まり）。
    始めは全部「これから／済み」で見えていて、語末 at_group でまとまり、at_unit でユニットが「いま」になる。"""
    y0, y1, gap = 290, 1030, 12
    gx, gw = 40, 700
    ux, uw = 820, 1060
    gh = (y1 - y0 - (len(groups) - 1) * gap) / len(groups)
    uh = (y1 - y0 - (len(units) - 1) * gap) / len(units)
    gys = [y0 + i * (gh + gap) for i in range(len(groups))]
    uys = [y0 + i * (uh + gap) for i in range(len(units))]
    for i, (y, n) in enumerate(zip(gys, groups)):
        _row(s, gx, y, gw, gh, n, "done" if i < gi else "todo", 3.2)
    for i, (y, n) in enumerate(zip(uys, units)):
        _row(s, ux, y, uw, uh, n, "done" if i < ui else "todo", 3.6)
    with s.reveal("group", at_group, "いまのまとまりを青に"):
        _row(s, gx, gys[gi], gw, gh, groups[gi], "now", 3.2)
        s.arrow(gx + gw + 4, gys[gi] + gh / 2, ux - 10, gys[gi] + gh / 2, 18, lead=False)   # このまとまりの中身が右の一覧
    with s.reveal("unit", at_unit, "いまのユニット（このレクチャー）を青に"):
        _row(s, ux, uys[ui], uw, uh, units[ui], "now", 3.6)


CSS_TEMPLATE = """    #root {
      position: absolute;
      inset: 0;
      overflow: hidden;
      container-type: size;
/*PALETTE*/
    }
    .§-ground { position: absolute; inset: 0; background-color: var(--paper); }
    .§-svg { position: absolute; inset: 0; width: 100%; height: 100%; display: block; }
    #root text { font-family: "BIZ UDPGothic", sans-serif; }
    .§-b { font-weight: 700; }
    .§-ink { fill: var(--ink); }
    .§-mute { fill: var(--mute); }
    .§-subj { fill: var(--subj); }
    .§-acc { fill: var(--acc); }
    .§-wht { fill: #FFFFFF; }
    .§-rule, .§-rule-b, .§-x-acc, .§-ok-subj {
      fill: none; stroke-linecap: round; stroke-linejoin: round;
    }
    .§-rule { stroke: var(--rule); stroke-width: 0.12cqw; }
    .§-rule-b { stroke: var(--rule); stroke-width: 0.24cqw; }
    /* 描画する線。dasharray は「1 2」— 「1 1」だと offset 1 で終点に丸キャップの点が残る */
    .§-draw { stroke-dasharray: 1 2; }
    .§-x-acc { stroke: var(--acc); stroke-width: 0.24cqw; }
    .§-ok-subj { stroke: var(--subj); stroke-width: 0.24cqw; }
    .§-acc-line { fill: none; stroke: var(--acc); stroke-width: 0.42cqw; stroke-linecap: round; }
    .§-tick { fill: none; stroke: var(--ink); stroke-width: 0.32cqw; stroke-linecap: round; }
    .§-head { fill: var(--rule); stroke: none; }
    .§-marker { fill: var(--subj); }
    .§-pill { fill: var(--ink); }
    .§-pip { fill: none; stroke: var(--rule); stroke-width: 0.12cqw; }
    .§-pip-on { fill: var(--ink); stroke: var(--ink); stroke-width: 0.12cqw; }
    .§-box { fill: var(--face); stroke: var(--rule); stroke-width: 0.12cqw; }
    .§-box-white { fill: #FFFFFF; stroke: var(--rule); stroke-width: 0.12cqw; }
    .§-box-subj { fill: var(--subj-face); stroke: var(--subj); stroke-width: 0.24cqw; }
    .§-box-acc { fill: var(--acc-face); stroke: var(--acc); stroke-width: 0.24cqw; }
    .§-box-ink { fill: var(--ink); stroke: none; }
    .§-solid-subj { fill: var(--subj); stroke: none; }
    .§-node { fill: #FFFFFF; stroke: var(--rule); stroke-width: 0.12cqw; }
    .§-leaf { fill: var(--subj); stroke: none; }
    .§-leaf-weak { fill: rgba(31, 43, 224, 0.6); stroke: none; }
    .§-mini { fill: var(--subj-face); stroke: var(--subj); stroke-width: 0.12cqw; }
    .§-bar-acc { fill: var(--acc); stroke: none; }
    .§-dot { fill: var(--subj); stroke: none; }
    .§-shot { fill: none; stroke: var(--rule); stroke-width: 0.12cqw; }
    .§-hl { fill: none; stroke: var(--subj); stroke-width: 0.42cqw; }
"""
