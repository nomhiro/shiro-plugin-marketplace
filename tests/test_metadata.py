import json
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
PLUGIN = REPO / "plugins" / "udemy-exam-prep"

# リリースするバージョン。marketplace.json と plugin.json の両方に同じ値が
# 入っていることを検証する（片方だけ上げる事故を落とすため、ここを唯一の定義元にする）
VERSION = "0.6.0"


def _load(p):
    return json.loads(p.read_text(encoding="utf-8"))


def test_marketplace_json_shape():
    m = _load(REPO / ".claude-plugin" / "marketplace.json")
    assert m["name"] == "shiro-plugin-marketplace"
    assert m["owner"]["name"] == "nomhiro"
    names = [p["name"] for p in m["plugins"]]
    assert names == ["udemy-exam-prep"]
    entry = m["plugins"][0]
    assert entry["source"] == "./plugins/udemy-exam-prep"
    assert entry["version"] == VERSION
    assert entry["description"].strip()


def test_the_two_manifests_declare_the_same_version():
    """片方だけ上げる事故を落とす。"""
    m = _load(REPO / ".claude-plugin" / "marketplace.json")
    p = _load(PLUGIN / ".claude-plugin" / "plugin.json")
    assert m["metadata"]["version"] == VERSION
    assert m["plugins"][0]["version"] == VERSION
    assert p["version"] == VERSION


def test_plugin_json_shape():
    p = _load(PLUGIN / ".claude-plugin" / "plugin.json")
    assert p["name"] == "udemy-exam-prep"
    assert p["version"] == VERSION
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
