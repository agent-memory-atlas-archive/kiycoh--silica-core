# SPDX-License-Identifier: MIT
# Copyright (C) 2026 Alessandro Carosia

"""scripts/bench_repl.py: an arm changes the search reply and nothing else."""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _mod():
    spec = importlib.util.spec_from_file_location("bench_repl", ROOT / "scripts" / "bench_repl.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class FakeSearch:
    name, description = "silica_search", "desc"

    def __init__(self):
        self.calls = []

    def json_schema(self):
        return {"function": {"name": self.name, "description": self.description,
                             "parameters": {"properties": {"width": {"default": 600}}}}}

    def run(self, **kw):
        self.calls.append(kw)
        return json.dumps({"hits": [{"path": "a.md", "matched_terms": ["x"], "coverage": 0.5, "window": "w"}],
                           "documents": [{"path": "a.md"}], "terms_absent": ["q"], "dense": {"state": "ready"}})


def test_arms_touch_only_what_they_name():
    b = _mod()
    base, lean, wide = (b.Shaped(FakeSearch(), arm) for arm in ("base", "lean", "wide"))

    assert json.loads(base.run(query="q")) == json.loads(base.tool.run(query="q"))
    assert base.json_schema()["function"]["parameters"]["properties"]["width"]["default"] == 600

    d = json.loads(lean.run(query="q"))
    assert "documents" not in d and "matched_terms" not in d["hits"][0]
    assert d["hits"][0]["coverage"] == 0.5 and d["terms_absent"] == ["q"] and d["dense"]["state"] == "ready"
    assert lean.json_schema() == base.json_schema()

    wide.run(query="q")
    wide.run(query="q", width=300)
    assert wide.tool.calls == [{"query": "q", "width": 1500}, {"query": "q", "width": 300}]
    assert wide.json_schema()["function"]["parameters"]["properties"]["width"]["default"] == 1500
    assert wide.tool.json_schema()["function"]["parameters"]["properties"]["width"]["default"] == 600  # the tool is untouched
    assert (base.description, lean.description, wide.description) == ("desc",) * 3
