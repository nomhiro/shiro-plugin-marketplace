import json
import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
PLUGIN = REPO / "plugins" / "udemy-exam-prep"

# 版の数字はテストに書かない（2026-11-27。テストの定数だけ上げ忘れて main で失敗が続いた）。
# 確かめるのは、marketplace.json の各エントリと各プラグインの plugin.json が同じ版を宣言していること。
SEMVER = re.compile(r"^\d+\.\d+\.\d+$")


def _load(p):
    return json.loads(p.read_text(encoding="utf-8"))


def test_marketplace_json_shape():
    m = _load(REPO / ".claude-plugin" / "marketplace.json")
    assert m["name"] == "shiro-plugin-marketplace"
    assert m["owner"]["name"] == "nomhiro"
    names = [p["name"] for p in m["plugins"]]
    assert "udemy-exam-prep" in names
    entry = next(p for p in m["plugins"] if p["name"] == "udemy-exam-prep")
    assert entry["source"] == "./plugins/udemy-exam-prep"
    assert entry["description"].strip()
    # 全エントリが最低限の形を満たすこと
    for e in m["plugins"]:
        assert e["source"].startswith("./plugins/")
        assert e["version"] and e["description"].strip()


def test_the_two_manifests_declare_the_same_version():
    """全プラグインで、marketplace.json のエントリと plugin.json の版が同じ（片方だけ上げる事故を落とす）。"""
    m = _load(REPO / ".claude-plugin" / "marketplace.json")
    assert SEMVER.match(m["metadata"]["version"])
    for e in m["plugins"]:
        p = _load(REPO / e["source"] / ".claude-plugin" / "plugin.json")
        assert p["name"] == e["name"]
        assert SEMVER.match(e["version"]), e["name"]
        assert p["version"] == e["version"], f'{e["name"]}: marketplace.json {e["version"]} / plugin.json {p["version"]}'


def test_plugin_json_shape():
    p = _load(PLUGIN / ".claude-plugin" / "plugin.json")
    assert p["name"] == "udemy-exam-prep"
    assert SEMVER.match(p["version"])
    assert p["description"].strip()
    assert p["author"]["name"] == "nomhiro"


def test_plugin_mcp_json_is_flat_map():
    m = _load(PLUGIN / ".mcp.json")
    # プラグイン root の .mcp.json は mcpServers ラッパーを持たない
    assert "mcpServers" not in m
    assert m["playwright"]["command"] == "npx"
    assert m["playwright"]["args"] == ["@playwright/mcp@latest"]


def test_license_is_mit():
    text = (REPO / "LICENSE").read_text(encoding="utf-8")
    assert "MIT License" in text
