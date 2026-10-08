# SPDX-License-Identifier: MIT
# Copyright (C) 2026 Alessandro Carosia

"""Skills: folders holding a SKILL.md that a silica loop expands into a turn
when a person types /<name> (ADR-0063 in the private tree).

The format is Agent Skills' (agentskills.io): YAML frontmatter with `name` and
`description`, Markdown instructions below it. Arguments follow Claude Code's
convention, so one file serves both: `$ARGUMENTS` is the text typed after the
name, `$ARGUMENTS[N]` and `$N` its N-th shell word (0-based), and a body where
no placeholder receives them gets `ARGUMENTS: <text>` appended.
`argument-hint` is what a picker shows; here it also marks the arguments a
skill cannot run without: every `<...>` outside a `[...]`.

Three roots, nearest first, and the first folder of a name wins, so a vault
or the home dir can shadow a built-in the way the distill profiles do:

    <vault>/.silica/skills/   this vault only
    ~/.silica/skills/         every vault
    builtin_skills/           this package

The built-ins are not under skills/: the plugin manifests hand that folder to
Claude Code and Codex, and these name tools the MCP server here does not
serve (silica_flag_note).

Nothing in a skill folder runs. Claude Code's !`command` injection is left
out because a vault can shadow a built-in, and a vault is not always its
reader's own: typing /explain in a shared vault would run its author's shell.
"""
from __future__ import annotations

import logging
import re
import shlex
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)

BUILTIN = Path(__file__).resolve().parent.parent / "builtin_skills"

# Agent Skills' name rule. The name is also the command and a path component,
# so it is enforced here rather than trusted from the folder.
_NAME = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*")
_PLACEHOLDER = re.compile(r"\$ARGUMENTS\[(\d+)\]|\$ARGUMENTS|\$(\d+)")
# Maintainer notes: the why of a clause sits beside it and never reaches the model.
_COMMENT = re.compile(r"<!--.*?-->[ \t]*\n?", re.S)
_warned: set[Path] = set()   # discovery reruns on every completion and expansion; a bad file says so once


@dataclass(frozen=True)
class Skill:
    name: str
    description: str
    argument_hint: str
    body: str
    source: str   # "vault" | "home" | "builtin"
    path: Path


def roots(vault: str | Path | None = None) -> list[tuple[str, Path]]:
    """(source, folder) pairs, nearest first."""
    from silica_core.kernel.recall import paths   # read per call: the test suite rebinds the home

    out = [("vault", Path(vault) / ".silica" / "skills")] if vault else []
    return out + [("home", paths._SILICA_HOME / "skills"), ("builtin", BUILTIN)]


def _skip(path: Path, why: str) -> None:
    if path not in _warned:
        _warned.add(path)
        logger.warning("skill %s skipped: %s", path, why)


def load(path: Path, source: str) -> Skill | None:
    """One SKILL.md, or None when it cannot be a command (logged once)."""
    from silica_core.kernel.write.frontmatter import split

    name = path.parent.name
    if len(name) > 64 or not _NAME.fullmatch(name):
        _skip(path, f"{name!r} is not a skill name (a-z, 0-9 and single hyphens)")
        return None
    try:
        data, _raw, body = split(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError) as e:
        _skip(path, str(e))
        return None
    if data is None:
        _skip(path, "no YAML frontmatter mapping")
        return None
    if data.get("name", name) != name:
        _skip(path, f"name {data.get('name')!r} differs from its folder {name!r}")
        return None
    hint = data.get("argument-hint") or ""
    if isinstance(hint, list):   # `argument-hint: [issue]` is a YAML list, Claude Code's own docs write it so
        hint = " ".join(f"[{h}]" for h in hint)
    return Skill(name, str(data.get("description") or "").strip(), str(hint).strip(),
                 body.strip(), source, path)


def discover(vault: str | Path | None = None) -> dict[str, Skill]:
    """Every skill reachable from `vault`, by name, sorted; the nearest root wins.

    ponytail: re-read on every call (a dozen small files), so an edited skill
    applies at its next use; cache by mtime if a root ever holds hundreds.
    """
    found: dict[str, Skill] = {}
    for source, root in roots(vault):
        if not root.is_dir():
            continue
        for path in sorted(root.glob("*/SKILL.md")):
            if path.parent.name in found:
                continue
            skill = load(path, source)
            if skill is not None:
                found[skill.name] = skill
    return dict(sorted(found.items()))


def _words(args: str) -> list[str]:
    try:
        return shlex.split(args)
    except ValueError:   # an apostrophe in prose ("dell'entropia") is not a quoting error
        return args.split()


def required(hint: str) -> int:
    """How many positional arguments `hint` marks required: its `<...>` outside `[...]`."""
    return len(re.findall(r"<[^>]*>", re.sub(r"\[[^\]]*\]", "", hint)))


def expand(skill: Skill, args: str = "") -> str:
    """The turn for `/<name> <args>`. Raises ValueError, carrying the usage
    line, when the hint marks an argument required and it is missing."""
    args = args.strip()
    words = _words(args)
    need = required(skill.argument_hint)
    if sum(1 for w in words if not w.startswith("-")) < need:
        raise ValueError(f"/{skill.name} needs {need} argument{'s' if need > 1 else ''}. "
                         f"Usage: /{skill.name} {skill.argument_hint}")
    received = False

    def fill(m: re.Match) -> str:
        nonlocal received
        if m.group(0) == "$ARGUMENTS":
            received = True
            return args
        i = int(m.group(1) or m.group(2))
        if i >= len(words):
            return m.group(0)   # Claude Code leaves an index with no argument as written
        received = True
        return words[i]

    body = _PLACEHOLDER.sub(fill, _COMMENT.sub("", skill.body)).strip()
    return f"{body}\n\nARGUMENTS: {args}" if args and not received else body
