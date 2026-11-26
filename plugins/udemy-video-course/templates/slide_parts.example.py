"""講座の slides.py で共通に使う部品の雛形（udemy-video-course プラグインの templates/ から写す）。

講座の `<parts_dir>/<講座>_parts.py`（`course.yaml` の parts_dir。既定 videos/_shared）に写し、CHAPTERS を講座の並びで埋める。
部品（box・white・callout・exam_row・opt・書体とはみ出しの検査）を、ユニットごとに写さず1か所にまとめる。

    # slides.py の先頭（unit_build.py が scripts と parts_dir を PYTHONPATH に入れて流す）
    from course_parts import *  # noqa
    from slide_kit import load_durations, Beats, render_pages, lesson_rows

形の約束: 青い札・青い字＝いま見ているもの（名前・答え・正解）／黒＝ふつうの札・矢印・説明／橙＝間違い（✗）だけ。
大きさは 5.0（大きな名前）・3.0（主役）・2.4（注・札の中）の3段。
compact の型（course.yaml の slide_style: compact。2026-11-26）は 5.0・2.4・2.0 の3段で、箱の寸法は文字から決め、
中身の塊の中心を画面の中央に置く（slide_kit の box_h・box_w・pair_geom・card_h・top_for。references/slide-format.md「compact の型」）。
"""
import math  # noqa: E402

import slide_kit  # noqa: E402
from slide_kit import Slide, COMPACT, PX, box_h, top_for  # noqa: E402,F401
from slide_kit import box_w, text_rows, pair_geom, card_h, card_line_y, card_w  # noqa: E402,F401

M, SM, BIG = (2.4, 2.0, 5.0) if COMPACT else (3.0, 2.4, 5.0)

# ── 現在地（章ごと）──────────────────────────────────────────────────────────
# {章番号: (章の名前, [まとまりの名前...], {まとまりの番号: [ユニットの名前...]})}
# ★ まとまりは **Udemy の並び**で書く。番号順で書くと、position() がまだ見ていないまとまりを「済み」で塗ることがある
CHAPTERS = {
    1: ("第1章 <章の名前>", ["<まとまり1>", "<まとまり2>"],
        {0: ["<ユニット1>", "<ユニット2>", "<ユニット3>"], 1: ["<ユニット1>", "<ユニット2>"]}),
}

def position(s, E, chapter: int, gi: int, ui: int, at_group: float, at_unit: float):
    """F1 現在地。gi・ui は 0 始まり。
    slide_kit.position_map と同じ段組みに、右の一覧（いまのまとまりの中身）をくくる「[」を足し、矢印は水平にそこへ当てる。"""
    _title, groups, units = CHAPTERS[chapter]
    units = units[gi]
    if COMPACT:
        # compact: 行の高さ・幅を文字から決め、左右・上下とも中央に置く（塊の中心が画面の中央。上端は top_for）
        gs, us = 2.4, 2.8
        gh = uh = box_h([us])
        gap = 16
        gw = math.ceil((max(s.fonts.width(n, gs, 700) for n in groups) + 150) / 20) * 20
        uw = math.ceil((max(s.fonts.width(n, us, 700) for n in units) + 150) / 20) * 20
        gx = (1920 - (gw + 100 + 36 + uw)) / 2
        ux = gx + gw + 100 + 36
        nmax = max(len(groups), len(units))
        y0 = top_for(nmax * gh + (nmax - 1) * gap)
        y1 = y0 + len(units) * uh + (len(units) - 1) * gap
    else:
        gs, us = 3.2, 3.6
        y0, y1, gap = 290, 1030, 12
        gx, gw = 40, 700
        ux, uw = 860, 1020
        gh = (y1 - y0 - (len(groups) - 1) * gap) / len(groups)
        uh = (y1 - y0 - (len(units) - 1) * gap) / len(units)
    gys = [y0 + i * (gh + gap) for i in range(len(groups))]
    uys = [y0 + i * (uh + gap) for i in range(len(units))]
    for i, (y, n) in enumerate(zip(gys, groups)):
        slide_kit._row(s, gx, y, gw, gh, n, "done" if i < gi else "todo", gs)
    for i, (y, n) in enumerate(zip(uys, units)):
        slide_kit._row(s, ux, y, uw, uh, n, "done" if i < ui else "todo", us)
    # 右の一覧をくくる「[」（初めから描く）。矢印は、いまのまとまりの行から水平に「[」へ当てる（再レビュー中: 斜めの矢印が済みの行を指して見えた）
    bx = ux - 36
    s.rect(bx, y0, 6, y1 - y0, "box-ink", 0)
    s.rect(bx, y0, 24, 6, "box-ink", 0)
    s.rect(bx, y1 - 6, 24, 6, "box-ink", 0)
    with s.reveal("group", at_group, "いまのまとまりを青に（中身の一覧への矢印）"):
        slide_kit._row(s, gx, gys[gi], gw, gh, groups[gi], "now", gs)
        s.arrow(gx + gw + 4, gys[gi] + gh / 2, bx - 10, gys[gi] + gh / 2, 18, lead=False)
    with s.reveal("unit", at_unit, "いまのユニット（このレクチャー）を青に"):
        slide_kit._row(s, ux, uys[ui], uw, uh, units[ui], "now", us)


# ── 書体に無い字・画面のはみ出しを、生成の時点で止める──────────
_text = Slide.text


def _text_checked(self, x, cy, s_, size, color="ink", anchor="middle", bold=False, fit=None, overlap=False):
    cmap = self.fonts._f[700 if bold else 400][0]
    for ch in s_:
        if not ch.isspace() and ord(ch) not in cmap:
            raise ValueError(f"{self.id}: 「{ch}」(U+{ord(ch):04X}) が書体に無い（{s_}）")
    w = _text(self, x, cy, s_, size, color, anchor, bold, fit, overlap)
    left = x if anchor == "start" else (x - w if anchor == "end" else x - w / 2)
    if left < 34 or left + w > 1886:
        raise ValueError(f"{self.id}: 「{s_}」が画面からはみ出す（{left:.0f}〜{left + w:.0f}px）")
    return w


Slide.text = _text_checked


# ── 部品 ────────────────────────────────────────────────────────────────────
def box(s, x, y, w, h, label, kind="box-white", color="ink", size=SM, bold=True, pad=36):
    s.rect(x, y, w, h, kind)
    s.text(x + w / 2, y + h / 2, label, size, color, bold=bold, fit=w - pad, overlap=True)


def white(s, x, y, w, h):
    s.rect(x, y, w, h, "wht", 0)


def wid(s, text, size=M, bold=True):
    return s.fonts.width(text, size, 700 if bold else 400)


def shot(s, href, x, y, w, max_h=None, clear=14):
    """画面のキャプチャを、切り出しの縦横比のまま置く。h は比率から決める（meet の余白で強調がずれないように）。
    max_h を渡すと (x, y, w, max_h) の枠に収める。超えるときは高さに合わせて縮めて横の中央に、足りないときは縦の中央に寄せる。
    先に白で周りを塗るので、同じ場所に描き直すと前の強調が消える（強調は一度に1つ）。
    返り値 hl(x0, y0, x1, y1) は、切り出しの画素の座標で強調の枠を当てる。hl.box は置いた (x, y, w, h)。"""
    from PIL import Image
    s.strict_order = True   # 描き直しの層が重なるので、reveal は時刻の順でないと前の枠が見えない（slide_kit.reveal が止める）
    cw, ch = Image.open(s.unit / href).size
    k = w / cw
    if max_h and ch * k > max_h:
        k = max_h / ch
        x += (w - cw * k) / 2
    elif max_h:
        y += (max_h - ch * k) / 2
    w, h = cw * k, ch * k
    white(s, x - clear, y - clear, w + 2 * clear, h + 2 * clear)
    s.image(x, y, w, h, href)

    def hl(x0, y0, x1, y1, pad=6):
        # 2026-10-19 L8-2 slide-reviewer 中（4か所）: 別の画像に枠を当てると、前の画像の枠が残って枠が2つになった。
        # 枠は一度に1つ: 前に枠を当てた別の画像を、枠なしで描き直してから当てる
        prev = getattr(s, "_gh_hl_shot", None)
        if prev and prev[0] != (href, x, y, w):
            p_href, p_x, p_y, p_w, p_h = prev[1]
            white(s, p_x - clear, p_y - clear, p_w + 2 * clear, p_h + 2 * clear)
            s.image(p_x, p_y, p_w, p_h, p_href)
        s._gh_hl_shot = ((href, x, y, w), (href, x, y, w, h))
        s.highlight(x + x0 * k - pad, y + y0 * k - pad, (x1 - x0) * k + 2 * pad, (y1 - y0) * k + 2 * pad)
    hl.box = (x, y, w, h)
    return hl


def callout(s, text, x=92, y=985, size=SM, color="ink"):
    """下の1行。同じ場所に重ねると、前の1行を白で隠して置き換わる。"""
    white(s, 60, y - 31, 1800, 62)
    return s.text(x, y, text, size, color, "start", bold=True, fit=1780, overlap=True)


def _ex_lines(s, x, cy, ex, color, fit):
    """説明を1行（str）か2行（list）で置く。2行の行送りは 66px（SM の約1.43倍。check_spacing の文の行 1.4 倍）。"""
    lines = [ex] if isinstance(ex, str) else list(ex)
    n = len(lines)
    pitch = round(SM * PX * 1.5) if COMPACT else 66
    for k, line in enumerate(lines):
        s.text(x, cy + (k - (n - 1) / 2) * pitch, line, SM, color, "start", bold=True, fit=fit, overlap=True)


SUM_NAME = 2.8 if COMPACT else M      # 要点の行の名前の大きさ


def _sum_geom(n_rows, n_lines, y0):
    """summary_rows・summary_late_line の共通の座標（行の高さ・隙間・上端）。"""
    if COMPACT:
        h = box_h([SUM_NAME]) if n_lines == 1 else box_h([SM] * n_lines)
        gap = 20
        if y0 is None:
            y0 = top_for(n_rows * h + (n_rows - 1) * gap)
    else:
        if y0 is None:
            y0 = 340 if n_rows <= 4 else 230
        gap = 24
        h = min(150, (1035 - y0 - gap * (n_rows - 1)) / n_rows)
    return h, gap, y0


def summary_rows(s, rows, split=760, y0=None):
    """要点の教材ページ。rows = [(名前, 説明, 語末, 注記)]。薄い行が始めから見え、語りに合わせて青く ✓。
    説明は str（1行）か list（2行。2026-10-18 L2-1: 地図の名前が長く、説明の欄が狭いとき）。
    y0 の既定は 4行まで 340、5行以上 230（2026-10-18 data-usage slide-reviewer 高: 5行で2行の説明が枠に接した）。
    compact では、行の高さを文字から決め、塊の中心を画面の中央に置く。"""
    n_lines = max(1 if isinstance(r[1], str) else len(r[1]) for r in rows)
    h, gap, y0 = _sum_geom(len(rows), n_lines, y0)
    ys = [y0 + i * (h + gap) for i in range(len(rows))]
    for y, (nm, ex, _at, _n) in zip(ys, rows):
        s.rect(40, y, 1840, h, "box")
        s.text(110, y + h / 2, nm, SUM_NAME, "mute", "start", bold=True, fit=split - 150, overlap=True)
        _ex_lines(s, split, y + h / 2, ex, "mute", 1780 - split)
    for i, (y, (nm, ex, at, note)) in enumerate(zip(ys, rows)):
        with s.reveal(f"sum{i + 1}", at, note):
            s.rect(40, y, 1840, h, "box-subj")
            s.text(110, y + h / 2, nm, SUM_NAME, "subj", "start", bold=True, fit=split - 150, overlap=True)
            _ex_lines(s, split, y + h / 2, ex, "ink", 1780 - split)
            s.check(1810, y + h / 2, 44)


def summary_late_line(s, n_rows, i, split, text, at, note, y0=None):
    """要点の i 行目（0 から）の2行目を、その文を語り始める語で後から出す（2026-10-20 L0-1 slide-reviewer 高: 2行目が行と一緒に出て、語りより早かった）。
    summary_rows には、その行の説明を [1行目, "　"]（全角の空白）で渡して2行ぶんの位置を取っておく。座標の決め方は summary_rows と同じ。"""
    h, gap, y0 = _sum_geom(n_rows, 2, y0)
    y = y0 + i * (h + gap)
    half = round(SM * PX * 1.5) / 2 if COMPACT else 33
    with s.reveal(f"late{i + 1}", at, note):
        s.text(split, y + h / 2 + half, text, SM, "ink", "start", bold=True, fit=1780 - split, overlap=True)


def exam_row(s, y, lines):
    """「試験」の札＋1〜3行。compact は札を 120×56 にし、行送りを M の 1.45 倍にする。"""
    if COMPACT:
        s.rect(90, y - 28, 120, 56, "pill", 28)
        tx, pitch = 250, round(M * PX * 1.45)
    else:
        s.rect(80, y - 34, 140, 68, "pill", 34)
        tx, pitch = 270, 82                                   # 行送り 1.42 倍
    s.text(150, y, "試験", SM, "wht", bold=True)
    n = len(lines)
    for k, t in enumerate(lines):
        s.text(tx, y + (k - (n - 1) / 2) * pitch, t, M, "ink", "start", bold=True, fit=1560)


def card(s, y, name, lines, kind="box-white", color="ink", n=None, x=None, w=None):
    """名前＋説明の行のカード（compact 用）。高さは card_h、幅は渡さなければ中身に合わせて左右の中央。
    n を渡すと、後から足す説明の行の分も高さを取る（足す行は card_line_y の位置に置く）。"""
    n = len(lines) if n is None else n
    if w is None:
        w = card_w(s, [(name, lines)], M, SM)
    if x is None:
        x = (1920 - w) / 2
    s.rect(x, y, w, card_h(n, M, SM), kind)
    tx = x + M * PX * 1.6
    s.text(tx, y + M * PX * 0.9 + M * PX / 2, name, M, color, "start", bold=True, overlap=True)
    for k, t in enumerate(lines):
        s.text(tx, card_line_y(y, k, M, SM), t, SM, "ink", "start", bold=True, fit=w - 2 * M * PX * 1.6, overlap=True)


# ── 考えてみよう（選択肢3つ）────────────────────────────────────────────────
OPT_X, OPT_W, OPT_H = 40, 1840, (104 if COMPACT else 120)   # compact: 高さ＝文字の 2.2 倍、隙間 16
OPT_Y = [400, 520, 640] if COMPACT else [520, 660, 800]
# 2026-10-18 ユーザー指示「読み上げるときはそれでいいけど、表示としては1,2,3でいい」: 語りは「ひとつ目」、画面の札は数字
OPT_LABELS = ["1", "2", "3"]


def opt(s, i, text, kind="box-white", size=SM):
    s.rect(OPT_X, OPT_Y[i], OPT_W, OPT_H, kind)
    s.text(OPT_X + 50, OPT_Y[i] + OPT_H / 2, OPT_LABELS[i], M, "subj", "start", bold=True, overlap=True)
    s.text(OPT_X + 140, OPT_Y[i] + OPT_H / 2, text, size, "ink", "start", bold=True, fit=1600, overlap=True)


def opt_mark(s, i, text, ok: bool, size=SM):
    """答えの枚: 正解は青の面＋✓、誤りは ✗ を右端に。size は問いの枚の opt と同じ値を渡す（違うと正解の札だけ字が変わる）。"""
    if ok:
        white(s, OPT_X - 4, OPT_Y[i] - 4, OPT_W + 8, OPT_H + 8)
        opt(s, i, text, "box-subj", size=size)
        s.check(OPT_X + OPT_W - 70, OPT_Y[i] + OPT_H / 2, 42)
    else:
        s.cross(OPT_X + OPT_W - 70, OPT_Y[i] + OPT_H / 2, 40)
