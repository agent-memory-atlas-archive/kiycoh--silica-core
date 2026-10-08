---
name: summarize
description: "Read-only digest of one or more documents, or a folder, from the folder silica-core indexes: core ideas first, tables for anything enumerable. Use when the user asks to summarize, digest or recap specific notes, files or a folder."
argument-hint: "<note|folder...>"
compatibility: "Requires the silica-core MCP server (silica_files, silica_search, silica_read)."
metadata:
  silica-core-managed: "true"
---
Summarize from the indexed folder: $ARGUMENTS

Resolve each target (note path, note title, or folder: list a folder with silica_files and read its notes with silica_read). Then write a digest in chat: lead with the core ideas, use tables for anything enumerable (comparisons, parameters, timelines), keep it scannable.
READ-ONLY: do not create, edit, patch, or move any note.
