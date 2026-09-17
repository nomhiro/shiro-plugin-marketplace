"""必須収録の照合・キーワードの問われ方検索・question-bank の貼り替え。"""
import textwrap

from scripts.check_must_include import (
    best_match, feature_words, load_course_rows, parse_items,
)
from scripts.finalize_section import refresh_bank
from scripts.find_in_books import find
from scripts.validate_quiz_csv import HEADER, write_rows


def quiz(tmp_path, section, rows):
    d = tmp_path / section
    d.mkdir(parents=True, exist_ok=True)
    p = d / "quiz.csv"
    write_rows(p, [list(HEADER)] + rows)
    return p


def row(question, options, correct, overall="出典: https://example.com/a", domain="D1"):
    r = [question, "multiple-choice" if "," not in str(correct) else "multi-select"]
    for k in range(6):
        r += [options[k], f"解説{k}"] if k < len(options) else ["", ""]
    r += [str(correct), overall, domain]
    return r


# --- 必須収録の照合 --------------------------------------------------------

def test_feature_words_skip_boilerplate():
    words = feature_words("RMSprop の説明として最も適切なものはどれか")
    assert "RMSprop" in words
    assert "適切" not in words


def test_q_and_a_lines_become_one_item(tmp_path):
    """Q と A が別行の資料は1件として数える。

    別々に数えると件数が倍になり、解答行が単独項目として
    「収録されていない」と大量に誤検出される（実績: 128件が256件になった）。
    """
    src = tmp_path / "must.md"
    src.write_text(textwrap.dedent("""\
        # 必須収録
        ### D001
        - **Q:** 「AI効果」とは、AIの成果を過大評価する現象である。○か×か。
        - **A:** ×。仕組みが分かると過小評価する現象。
        ### D002
        - **Q:** ダートマス会議の主催者と開催年。
        - **A:** ジョン・マッカーシー、1956年。
    """), encoding="utf-8")
    items = parse_items(src)
    assert len(items) == 2
    assert "AI効果" in items[0][0]
    assert "過小評価" in items[0][1]


def test_answer_side_words_find_the_question(tmp_path):
    """設問の言い回しが変わっても、答えの用語で拾える。

    短答を4択化すると設問文はまったく別物になるため、
    設問側だけで測ると収録済みの問題を取りこぼす。
    """
    quiz(tmp_path, "section01-mock-exam-1", [
        row("勾配の二乗の移動平均で学習率を調整する手法はどれか。",
            ["RMSprop", "AdaGrad", "Momentum", "Adam"], 1),
    ])
    rows = load_course_rows(str(tmp_path / "section0*" / "quiz.csv"))
    item = ("学習率を自動調整する代表的な最適化手法の名前。", "RMSprop。")
    score, _, no, _ = best_match(item, rows)
    assert no == 1
    assert score >= 0.5


def test_parse_items_reads_table_rows(tmp_path):
    src = tmp_path / "must.md"
    src.write_text(textwrap.dedent("""\
        | # | 論点 | 補足 |
        |---|---|---|
        | 1 | ダートマス会議 | 1956年・マッカーシー |
    """), encoding="utf-8")
    items = parse_items(src)
    assert len(items) == 1
    assert "ダートマス会議" in items[0][0]


# --- キーワードの問われ方 --------------------------------------------------

def test_find_in_books_separates_answer_from_distractor(tmp_path):
    quiz(tmp_path, "section01-mock-exam-1", [
        row("オープン・イノベーションの説明として最も適切なものはどれか。",
            ["外部の知見を取り込む", "社内のみで開発する", "特許を放棄する", "研究を停止する"], 1),
        row("産学連携の説明として最も適切なものはどれか。",
            ["大学と企業が共同研究する", "オープン・イノベーション", "外注する", "買収する"], 1),
    ])
    hits = find("オープン・イノベーション", str(tmp_path / "section0*" / "quiz.csv"), False)
    assert len(hits) == 2
    assert "問題文" in hits[0]["where"]
    assert "誤答肢" in hits[1]["where"]


def test_find_in_books_answers_only_filters(tmp_path):
    quiz(tmp_path, "section01-mock-exam-1", [
        row("Q1", ["ランダムフォレスト", "b", "c", "d"], 1),
        row("Q2", ["a", "ランダムフォレスト", "c", "d"], 1),
    ])
    hits = find("ランダムフォレスト", str(tmp_path / "section0*" / "quiz.csv"), True)
    assert len(hits) == 1
    assert hits[0]["q"] == 1


# --- question-bank の貼り替え ----------------------------------------------

def _section_with_bank_rows(tmp_path, name, rows_md):
    d = tmp_path / name / "_parts"
    d.mkdir(parents=True, exist_ok=True)
    (d / "bank-rows.md").write_text(rows_md, encoding="utf-8")
    return tmp_path / name


def test_refresh_bank_is_idempotent(tmp_path):
    """何回実行しても行が増えない。

    旧版は `| section0N |` の有無で追記かスキップを決めていたため、
    取りこぼすと同じセクションの行が二重に入り、概念の再利用回数が倍になった。
    """
    bank = tmp_path / "question-bank.md"
    bank.write_text("| section | q# | domain |\n|---|---|---|\n", encoding="utf-8")
    section = _section_with_bank_rows(
        tmp_path, "section01-drill-1",
        "| section01 | Q1 | D1 | T1 | 概念A | knowledge | 問題文A |\n"
        "| section01 | Q2 | D1 | T1 | 概念B | knowledge | 問題文B |\n")

    removed, added = refresh_bank(bank, section)
    assert (removed, added) == (0, 2)
    first = bank.read_text(encoding="utf-8")

    removed, added = refresh_bank(bank, section)
    assert (removed, added) == (2, 2)
    assert bank.read_text(encoding="utf-8") == first


def test_refresh_bank_replaces_stale_rows(tmp_path):
    """問題を差し替えたら bank の内容も入れ替わる（古い概念が残らない）。"""
    bank = tmp_path / "question-bank.md"
    bank.write_text(
        "| section | q# | domain |\n|---|---|---|\n"
        "| section01 | Q1 | D1 | T1 | 古い概念 | knowledge | 古い問題文 |\n"
        "| section02 | Q1 | D2 | T2 | 別セクション | knowledge | 触らない |\n",
        encoding="utf-8")
    section = _section_with_bank_rows(
        tmp_path, "section01-drill-1",
        "| section01 | Q1 | D1 | T1 | 新しい概念 | knowledge | 新しい問題文 |\n")

    refresh_bank(bank, section)
    text = bank.read_text(encoding="utf-8")
    assert "古い概念" not in text
    assert "新しい概念" in text
    assert "別セクション" in text          # 他セクションは残る


def test_refresh_bank_keeps_position(tmp_path):
    """貼り替えても他セクションとの順序が入れ替わらない。"""
    bank = tmp_path / "question-bank.md"
    bank.write_text(
        "| section01 | Q1 | D1 | T1 | 旧 | knowledge | x |\n"
        "| section02 | Q1 | D2 | T2 | 二番目 | knowledge | y |\n",
        encoding="utf-8")
    section = _section_with_bank_rows(
        tmp_path, "section01-drill-1",
        "| section01 | Q1 | D1 | T1 | 新 | knowledge | x |\n")
    refresh_bank(bank, section)
    lines = [l for l in bank.read_text(encoding="utf-8").splitlines() if l.strip()]
    assert lines[0].split("|")[1].strip() == "section01"
    assert lines[1].split("|")[1].strip() == "section02"
