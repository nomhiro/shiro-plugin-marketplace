"""講座の slides.py で共通に使う部品の雛形（udemy-video-course プラグインの templates/ から写す）。

講座の `<parts_dir>/<講座>_parts.py`（`course.yaml` の parts_dir。既定 videos/_shared）に写し、CHAPTERS を講座の並びで埋める。
部品（box・white・callout・exam_row・opt・書体とはみ出しの検査）を、ユニットごとに写さず1か所にまとめる。

    # slides.py の先頭（unit_build.py が scripts と parts_dir を PYTHONPATH に入れて流す）
    from course_parts import *  # noqa
    from slide_kit import load_durations, Beats, render_pages, lesson_rows

形の約束: 青い札・青い字＝いま見ているもの（名前・答え・正解）／黒＝ふつうの札・矢印・説明／橙＝間違い（✗）だけ。
大きさは 5.0（大きな名前）・3.0（主役）・2.4（注・札の中）の3段。
"""
import slide_kit  # noqa: E402
from slide_kit import Slide  # noqa: E402

M, SM, BIG = 3.0, 2.4, 5.0

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
    y0, y1, gap = 290, 1030, 12
    gx, gw = 40, 700
    ux, uw = 860, 1020
    gh = (y1 - y0 - (len(groups) - 1) * gap) / len(groups)
    uh = (y1 - y0 - (len(units) - 1) * gap) / len(units)
    gys = [y0 + i * (gh + gap) for i in range(len(groups))]
    uys = [y0 + i * (uh + gap) for i in range(len(units))]
    for i, (y, n) in enumerate(zip(gys, groups)):
        slide_kit._row(s, gx, y, gw, gh, n, "done" if i < gi else "todo", 3.2)
    for i, (y, n) in enumerate(zip(uys, units)):
        slide_kit._row(s, ux, y, uw, uh, n, "done" if i < ui else "todo", 3.6)
    # 右の一覧をくくる「[」（初めから描く）。矢印は、いまのまとまりの行から水平に「[」へ当てる（再レビュー中: 斜めの矢印が済みの行を指して見えた）
    bx = ux - 36
    s.rect(bx, y0, 6, y1 - y0, "box-ink", 0)
    s.rect(bx, y0, 24, 6, "box-ink", 0)
    s.rect(bx, y1 - 6, 24, 6, "box-ink", 0)
    with s.reveal("group", at_group, "いまのまとまりを青に（中身の一覧への矢印）"):
        slide_kit._row(s, gx, gys[gi], gw, gh, groups[gi], "now", 3.2)
        s.arrow(gx + gw + 4, gys[gi] + gh / 2, bx - 10, gys[gi] + gh / 2, 18, lead=False)
    with s.reveal("unit", at_unit, "いまのユニット（このレクチャー）を青に"):
        slide_kit._row(s, ux, uys[ui], uw, uh, units[ui], "now", 3.6)


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
    for k, line in enumerate(lines):
        s.text(x, cy + (k - (n - 1) / 2) * 66, line, SM, color, "start", bold=True, fit=fit, overlap=True)


def summary_rows(s, rows, split=760, y0=None):
    """要点の教材ページ。rows = [(名前, 説明, 語末, 注記)]。薄い行が始めから見え、語りに合わせて青く ✓。
    説明は str（1行）か list（2行。2026-10-18 L2-1: 地図の名前が長く、説明の欄が狭いとき）。
    y0 の既定は 4行まで 340、5行以上 230（2026-10-18 data-usage slide-reviewer 高: 5行で2行の説明が枠に接した）。"""
    if y0 is None:
        y0 = 340 if len(rows) <= 4 else 230
    h = min(150, (1035 - y0 - 24 * (len(rows) - 1)) / len(rows))
    ys = [y0 + i * (h + 24) for i in range(len(rows))]
    for y, (nm, ex, _at, _n) in zip(ys, rows):
        s.rect(40, y, 1840, h, "box")
        s.text(110, y + h / 2, nm, M, "mute", "start", bold=True, fit=split - 150, overlap=True)
        _ex_lines(s, split, y + h / 2, ex, "mute", 1780 - split)
    for i, (y, (nm, ex, at, note)) in enumerate(zip(ys, rows)):
        with s.reveal(f"sum{i + 1}", at, note):
            s.rect(40, y, 1840, h, "box-subj")
            s.text(110, y + h / 2, nm, M, "subj", "start", bold=True, fit=split - 150, overlap=True)
            _ex_lines(s, split, y + h / 2, ex, "ink", 1780 - split)
            s.check(1810, y + h / 2, 44)


def summary_late_line(s, n_rows, i, split, text, at, note, y0=None):
    """要点の i 行目（0 から）の2行目を、その文を語り始める語で後から出す（2026-10-20 L0-1 slide-reviewer 高: 2行目が行と一緒に出て、語りより早かった）。
    summary_rows には、その行の説明を [1行目, "　"]（全角の空白）で渡して2行ぶんの位置を取っておく。座標の決め方は summary_rows と同じ。"""
    if y0 is None:
        y0 = 340 if n_rows <= 4 else 230
    h = min(150, (1035 - y0 - 24 * (n_rows - 1)) / n_rows)
    y = y0 + i * (h + 24)
    with s.reveal(f"late{i + 1}", at, note):
        s.text(split, y + h / 2 + 33, text, SM, "ink", "start", bold=True, fit=1780 - split, overlap=True)


def exam_row(s, y, lines):
    """「試験」の札＋1〜3行。"""
    s.rect(80, y - 34, 140, 68, "pill", 34)
    s.text(150, y, "試験", SM, "wht", bold=True)
    n = len(lines)
    for k, t in enumerate(lines):
        s.text(270, y + (k - (n - 1) / 2) * 82, t, M, "ink", "start", bold=True, fit=1560)   # 行送り 1.42 倍


# ── 考えてみよう（選択肢3つ）────────────────────────────────────────────────
OPT_X, OPT_W, OPT_H = 40, 1840, 120
OPT_Y = [520, 660, 800]
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
