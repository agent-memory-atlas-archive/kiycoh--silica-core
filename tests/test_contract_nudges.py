# SPDX-License-Identifier: MIT
# Copyright (C) 2026 Alessandro Carosia

"""The two ways the plugin asks to be used: `silica-core setup claude`
puts its block into CLAUDE.md once, between markers; the search description
opens with the ask and stays under Claude Code's comfortable size."""
from __future__ import annotations

import re


def test_setup_claude_writes_its_block_once(tmp_path, monkeypatch):
    from silica_core.onboarding import guidance as g
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path))
    path = g.claude_md_path()
    assert path == tmp_path / "CLAUDE.md"
    assert g.write_guidance(path) == "created" and path.read_text().startswith(g.START)
    path.write_text("# mine\n\nkeep this\n" + path.read_text() + "\nand this\n")
    assert g.write_guidance(path) == "replaced"
    text = path.read_text()
    assert text.count(g.START) == 1 and text.startswith("# mine") and text.rstrip().endswith("and this")
    path.write_text("# only mine\n")
    assert g.write_guidance(path) == "appended" and path.read_text().startswith("# only mine\n\n" + g.START)


CAP = 1500  # a drift stop, not a measured cliff: 1,047 and 2,046 chars measured at parity (2026-09-11 A/B, 120 runs)


def test_search_description_opens_with_the_ask_and_fits():
    from silica_core.ui.mcp import exposed_tools
    d = exposed_tools(False)["silica_search"].description
    assert d.startswith("For a question that names no identifier") and "Do not grep for the words of a question" in d
    assert len(d) < CAP, f"silica_search description is {len(d)} chars, over the {CAP} cap by {len(d) - CAP + 1}"


def test_no_contract_surface_says_blocked():
    """A bare "blocked" reads as a policy restriction and the model gives
    up instead of taking the alternative (context-mode ADR-0003: 6/6
    capitulations with it, 0/6 with "redirected"). The one token with a
    measured cost; the list grows only with a number of its own."""
    from silica_core.onboarding.guidance import GUIDANCE
    from silica_core.ui.mcp import exposed_tools
    surfaces = {name: t.description for name, t in exposed_tools(False).items()}
    surfaces["guidance"] = GUIDANCE
    for name, text in surfaces.items():
        assert not re.search(r"\bblocked\b", text, re.I), f"{name} says 'blocked'"


def test_the_mod_serves_the_guidance_block_verbatim():
    # hooks/guidance.ts is generated from guidance.GUIDANCE, so the system-prompt
    # section the mod adds and the CLAUDE.md block never drift apart
    import json
    from pathlib import Path
    from silica_core.onboarding import guidance as g
    ts = (Path(__file__).resolve().parent.parent / "hooks" / "guidance.ts").read_text(encoding="utf-8")
    m = re.search(r"^export const GUIDANCE = (.+)$", ts, re.M)
    assert m, "hooks/guidance.ts must export GUIDANCE as one JSON string literal"
    assert json.loads(m.group(1)) == g.GUIDANCE, (
        "regenerate: python -c \"import json; from silica_core.onboarding.guidance import GUIDANCE; "
        "print('export const GUIDANCE = ' + json.dumps(GUIDANCE))\" > hooks/guidance.ts")
    assert g.START in ts, "the marker the mod looks for in CLAUDE.md is exported beside it"
