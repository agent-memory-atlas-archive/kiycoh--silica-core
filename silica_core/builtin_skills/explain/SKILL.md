---
name: explain
description: explain a concept grounded in the vault, at the chosen register
argument-hint: '"<concept>" [--level=intro|expert]'
metadata:
  internal: true
---
Explain from the vault: $ARGUMENTS

Write for a practitioner: clear, correct, minimal jargon. If the arguments carry --level=intro, write for a newcomer instead: plain language, concrete analogies, no unexplained jargon. If they carry --level=expert, write for an expert: precise and technical, no hand-holding.
Search the vault (semantic search + related notes), read the top matches, and explain the concept in chat, citing every note you drew on as a [[wikilink]]. If the vault has nothing relevant, say so plainly: do not silently answer from general knowledge alone.
<!-- The attribution clause is a measured defect of this command, not a guess:
evals/probe_explain_spans.py in the private tree (2026-07-26, 398 claims) found
~4.6% of claims attributed to a named note that does not support them, and as
many drawn from general knowledge with no note at all. -->
Attribute a claim to a note only if that note states it. A note that merely sits near the topic is not a source for it, and a point no note supports goes in its own sentence, marked as not coming from the vault.
READ-ONLY: do not create, edit, patch, or move any note.
