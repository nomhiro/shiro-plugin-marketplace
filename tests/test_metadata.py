import json
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
PLUGIN = REPO / "plugins" / "udemy-exam-prep"

# このプラグインのリリース版。marketplace.json の該当エントリと plugin.json の
# 両方に同じ値が入っていることを検証する（片方だけ上げる事故を落とす）。
VERSION = "0.6.0"
# マーケットプレイス自体の版。プラグインを足したら上げる
MARKETPLACE_VERSION = "0.7.0"


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
    assert entry["version"] == VERSION
    assert entry["description"].strip()
    # 全エントリが最低限の形を満たすこと
    for e in m["plugins"]:
        assert e["source"].startswith("./plugins/")
        assert e["version"] and e["description"].strip()


def test_the_two_manifests_declare_the_same_version():
    """片方だけ上げる事故を落とす。"""
    m = _load(REPO / ".claude-plugin" / "marketplace.json")
    p = _load(PLUGIN / ".claude-plugin" / "plugin.json")
    assert m["metadata"]["version"] == MARKETPLACE_VERSION
    entry = next(x for x in m["plugins"] if x["name"] == "udemy-exam-prep")
    assert entry["version"] == VERSION
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
