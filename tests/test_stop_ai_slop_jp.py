import json
import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
PLUGIN = REPO / "plugins" / "stop-ai-slop-jp"
SKILL = PLUGIN / "skills" / "stop-ai-slop-jp"
VERSION = "0.1.1"


def _load(p):
    return json.loads(p.read_text(encoding="utf-8"))


def test_manifests_declare_the_same_version():
    m = _load(REPO / ".claude-plugin" / "marketplace.json")
    entry = next(x for x in m["plugins"] if x["name"] == "stop-ai-slop-jp")
    p = _load(PLUGIN / ".claude-plugin" / "plugin.json")
    assert entry["source"] == "./plugins/stop-ai-slop-jp"
    assert entry["version"] == VERSION and p["version"] == VERSION
    assert p["name"] == "stop-ai-slop-jp"
    assert p["description"].strip()


def test_upstream_author_and_license_are_kept():
    """取り込んだものなので、原著者と MIT の著作権表示を落とさない。"""
    p = _load(PLUGIN / ".claude-plugin" / "plugin.json")
    assert p["author"]["name"] == "Daichi Nagashima"
    assert p["license"] == "MIT"
    assert p["repository"] == "https://github.com/iKora128/stop-ai-slop-jp"
    text = (PLUGIN / "LICENSE").read_text(encoding="utf-8")
    assert text.startswith("MIT License")
    assert "Daichi Nagashima" in text


def test_skill_front_matter_matches_its_directory():
    lines = (SKILL / "SKILL.md").read_text(encoding="utf-8").splitlines()
    assert lines[0].strip() == "---"
    end = next(i for i, l in enumerate(lines[1:], 1) if l.strip() == "---")
    fm = "\n".join(lines[1:end])
    assert re.search(r"^name:\s*stop-ai-slop-jp\s*$", fm, re.M)
    assert re.search(r"^description:\s*\S+", fm, re.M)


def test_every_reference_the_skill_mentions_exists():
    text = (SKILL / "SKILL.md").read_text(encoding="utf-8")
    refs = set(re.findall(r"references/[\w.-]+\.md", text))
    assert refs, "SKILL.md が references を1つも挙げていない"
    for r in refs:
        assert (SKILL / r).exists(), f"{r} がない"
