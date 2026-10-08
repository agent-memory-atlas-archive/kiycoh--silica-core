# SPDX-License-Identifier: MIT
# Copyright (C) 2026 Alessandro Carosia

"""Skills: discovery over the three roots and the expansion of /<name> <args>."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from silica_core.kernel import skills
from silica_core.kernel.write.frontmatter import split

ROOT = Path(__file__).resolve().parent.parent
BUILTINS = {"compare", "diagram", "explain", "relate", "schematize", "summarize"}


def _skill(root: Path, folder: str, body: str = "Do it: $ARGUMENTS", **front) -> Path:
    front.setdefault("name", folder)
    front.setdefault("description", f"the {folder} skill")
    lines = "".join(f"{k}: {json.dumps(v)}\n" for k, v in front.items())
    path = root / folder / "SKILL.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"---\n{lines}---\n{body}\n", encoding="utf-8")
    return path


def test_the_builtins_are_the_converted_commands_and_not_the_plugin_skill():
    found = skills.discover(None)
    assert set(found) == BUILTINS
    assert {s.source for s in found.values()} == {"builtin"}
    assert "silica" not in found   # the skill other agents load is not a command here


def test_no_builtin_sits_where_the_plugin_manifests_look():
    """Both manifests hand their `skills` folder to Claude Code and Codex. A
    built-in there would ship to every plugin user, naming silica_flag_note,
    which this package's server does not serve."""
    for manifest in (".claude-plugin/plugin.json", ".codex-plugin/plugin.json"):
        served = (ROOT / json.loads((ROOT / manifest).read_text())["skills"]).resolve()
        assert not skills.BUILTIN.resolve().is_relative_to(served), manifest


def test_every_builtin_is_hidden_from_npx_skills():
    """`npx skills add kiycoh/silica-core` falls back to a recursive search,
    which would offer these next to the plugin skill; `metadata.internal`
    keeps them out unless INSTALL_INTERNAL_SKILLS=1."""
    for path in skills.BUILTIN.glob("*/SKILL.md"):
        data, _, _ = split(path.read_text(encoding="utf-8"))
        assert data["metadata"]["internal"] is True, path


def test_nearest_root_wins(tmp_path, monkeypatch):
    from silica_core.kernel.recall import paths

    vault = tmp_path / "vault"
    _skill(vault / ".silica" / "skills", "explain", "vault explain")
    _skill(paths._SILICA_HOME / "skills", "explain", "home explain")
    _skill(paths._SILICA_HOME / "skills", "weekly", "home weekly")
    found = skills.discover(vault)
    assert (found["explain"].source, found["explain"].body) == ("vault", "vault explain")
    assert found["weekly"].source == "home"
    assert found["summarize"].source == "builtin"
    assert skills.discover(None)["explain"].source == "home"


def test_a_bad_skill_is_skipped_not_fatal(tmp_path, caplog):
    root = tmp_path / ".silica" / "skills"
    _skill(root, "Bad_Name")
    _skill(root, "renamed", name="other")
    (root / "nofront").mkdir()
    (root / "nofront" / "SKILL.md").write_text("just text\n", encoding="utf-8")
    _skill(root, "fine")
    found = skills.discover(tmp_path)
    assert "fine" in found
    assert not {"Bad_Name", "renamed", "other", "nofront"} & set(found)
    assert sum("skipped:" in r.getMessage() for r in caplog.records) == 3


def test_arguments_fill_the_placeholder_or_are_appended(tmp_path):
    root = tmp_path / ".silica" / "skills"
    _skill(root, "plain", "No placeholder here.")
    _skill(root, "pos", "Move $0 to $ARGUMENTS[1], keep $2.")
    found = skills.discover(tmp_path)
    assert skills.expand(found["plain"], "a b") == "No placeholder here.\n\nARGUMENTS: a b"
    assert skills.expand(found["plain"], "") == "No placeholder here."
    assert skills.expand(found["pos"], '"x y" z') == "Move x y to z, keep $2."


def test_a_missing_required_argument_is_the_usage_line(tmp_path):
    found = skills.discover(None)
    with pytest.raises(ValueError, match=r"Usage: /compare \"<A>\" \"<B>\" \[\.\.\.\]"):
        skills.expand(found["compare"], "RAG")
    with pytest.raises(ValueError, match="needs 1 argument"):
        skills.expand(found["explain"], "--level=intro")   # a flag is not the concept
    assert skills.required("<note|folder|topic> [--save=<path>]") == 1


def test_an_apostrophe_is_prose_not_a_quote():
    out = skills.expand(skills.discover(None)["explain"], "dell'entropia --level=intro")
    assert "dell'entropia --level=intro" in out


def test_maintainer_comments_never_reach_the_model():
    """explain carries the measurement behind its attribution clause beside
    the clause; the model gets the clause alone."""
    out = skills.expand(skills.discover(None)["explain"], "backpropagation")
    assert "Attribute a claim to a note only if that note states it" in out
    assert "<!--" not in out and "probe_explain_spans" not in out


def test_a_yaml_list_hint_reads_as_written(tmp_path):
    path = tmp_path / ".silica" / "skills" / "fix" / "SKILL.md"
    path.parent.mkdir(parents=True)
    path.write_text("---\nname: fix\nargument-hint: [issue]\n---\nFix $ARGUMENTS\n", encoding="utf-8")
    assert skills.discover(tmp_path)["fix"].argument_hint == "[issue]"


def test_a_session_title_shows_the_arguments():
    """A chat is titled by the first line of its first user turn, cut at 58
    characters (narration._title_from in the private tree). With the
    arguments past that cut, every /explain chat was listed under the same
    "Explain this concept groun..." (seen in the GUI on 2026-10-06)."""
    for s in skills.discover(None).values():
        first = skills.expand(s, "x y").splitlines()[0]
        assert "x y" in first[:58], s.name
