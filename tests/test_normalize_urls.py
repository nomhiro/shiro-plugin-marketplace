from scripts.normalize_urls import (
    LOCALE_RULES, normalize_file, normalize_rows, normalize_text,
)
from scripts.validate_quiz_csv import HEADER, read_rows, write_rows


def test_adds_a_missing_locale_segment():
    out, n = normalize_text("https://docs.claude.com/docs/claude-code/settings")
    assert out == "https://docs.claude.com/en/docs/claude-code/settings"
    assert n == 1


def test_replaces_a_wrong_locale_segment():
    out, _ = normalize_text("https://learn.microsoft.com/ja-jp/azure/ai-foundry/")
    assert out == "https://learn.microsoft.com/en-us/azure/ai-foundry/"


def test_is_idempotent():
    once, _ = normalize_text("https://docs.claude.com/docs/x")
    twice, n = normalize_text(once)
    assert twice == once
    assert n == 0


def test_preserves_the_anchor_and_query():
    out, _ = normalize_text("https://docs.claude.com/docs/x?a=1#frag")
    assert out == "https://docs.claude.com/en/docs/x?a=1#frag"


def test_leaves_locale_less_sites_untouched():
    url = "https://developers.cloudflare.com/workers/runtime-apis/"
    assert normalize_text(url) == (url, 0)
    assert LOCALE_RULES["developers.cloudflare.com"] is None


def test_leaves_unknown_hosts_untouched():
    url = "https://example.com/whatever/page"
    assert normalize_text(url) == (url, 0)


def test_does_not_touch_plain_prose():
    text = "Claude Code の設定は CLAUDE.md に書く。docs.claude.com という語自体は URL ではない。"
    assert normalize_text(text)[1] == 0


def test_normalizes_every_cell_of_every_row():
    rows = [
        list(HEADER),
        ["Q", "multiple-choice"] + ["o", "https://docs.claude.com/docs/a"] * 2
        + ["", ""] * 4 + ["1", "see https://learn.microsoft.com/fr-fr/azure/x", "D"],
    ]
    out, n = normalize_rows(rows)
    assert n == 3
    assert "docs.claude.com/en/docs/a" in out[1][3]
    assert "learn.microsoft.com/en-us/azure/x" in out[1][15]


def test_normalize_file_rewrites_in_place(tmp_path):
    p = tmp_path / "quiz.csv"
    row = ["Q", "multiple-choice"]
    for i in range(6):
        row += ([f"OPT{i + 1}", f"EXP{i + 1}"] if i < 4 else ["", ""])
    row += ["1", "Source: https://docs.claude.com/docs/tool-use", "Domain 1"]
    write_rows(p, [list(HEADER), row])

    assert normalize_file(p) == 1
    assert "docs.claude.com/en/docs/tool-use" in read_rows(p)[1][15]
    assert normalize_file(p) == 0  # 冪等


def test_normalize_file_keeps_the_file_bom_free(tmp_path):
    p = tmp_path / "quiz.csv"
    row = ["Q", "multiple-choice"]
    for i in range(6):
        row += ([f"OPT{i + 1}", f"EXP{i + 1}"] if i < 4 else ["", ""])
    row += ["1", "https://docs.claude.com/docs/a", "Domain 1"]
    write_rows(p, [list(HEADER), row])
    normalize_file(p)
    assert not p.read_bytes().startswith(b"\xef\xbb\xbf")
