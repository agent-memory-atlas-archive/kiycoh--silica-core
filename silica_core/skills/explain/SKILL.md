---
name: explain
description: "Explain a concept from the documents silica-core indexes in this folder, citing each passage it draws on. Use when the user asks what something means or how it works and the answer should come from these files rather than general knowledge; --level=intro or --level=expert sets the register."
argument-hint: '"<concept>" [--level=intro|expert]'
compatibility: "Requires the silica-core MCP server (silica_search, silica_read)."
metadata:
  silica-core-managed: "true"
---
Explain from the indexed folder: $ARGUMENTS

Write for a practitioner: clear, correct, minimal jargon. If the arguments carry --level=intro, write for a newcomer instead: plain language, concrete analogies, no unexplained jargon. If they carry --level=expert, write for an expert: precise and technical, no hand-holding.
Search with silica_search, read the top matches with silica_read, and explain the concept in chat, citing every passage you drew on by path and line (as a [[wikilink]] in a vault of notes). If the folder has nothing relevant, say so plainly: do not silently answer from general knowledge alone.
<!-- The attribution clause is a measured defect of this command, not a guess:
evals/probe_explain_spans.py in the private tree (2026-07-26, 398 claims) found
~4.6% of claims attributed to a named note that does not support them, and as
many drawn from general knowledge with no note at all. -->
Attribute a claim to a note only if that note states it. A note that merely sits near the topic is not a source for it, and a point no note supports goes in its own sentence, marked as not coming from these documents.
READ-ONLY: do not create, edit, patch, or move any note.
