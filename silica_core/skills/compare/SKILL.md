---
name: compare
description: "Comparison table of two or more documents or concepts from the folder silica-core indexes, with similarities, differences and any contradiction between them called out. Use when the user asks how A and B differ, which to choose, or whether the sources agree."
argument-hint: '"<A>" "<B>" [...]'
compatibility: "Requires the silica-core MCP server (silica_search, silica_read)."
metadata:
  silica-core-managed: "true"
---
Compare from the indexed folder: $ARGUMENTS

Each subject is a note (path or title) or a concept: locate and read the matching note(s) for each. Output in chat: a comparison table (one column per subject, dimensions as rows), then a short similarities/differences rundown. If any involved note carries `contested: true`, or the notes contradict each other, call that out explicitly. Cite each subject's passages by path and line.
READ-ONLY: do not create, edit, patch, or move any note.
