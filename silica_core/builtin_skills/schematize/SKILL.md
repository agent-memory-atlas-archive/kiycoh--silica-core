---
name: schematize
description: Markdown table schematizing a note, folder, or topic
argument-hint: "<note|folder|topic> [--save=<path>]"
metadata:
  internal: true
---
Schematize from the vault: $ARGUMENTS

Resolve the target: it may be a note (path or title), a folder (list and skim its notes), or a general topic (search the vault, then read the top matches).
Output in chat: a one-line caption, then a Markdown table whose rows/columns best decompose what you found (components, phases, comparison dimensions, whatever shape fits); do not force a fixed template.
READ-ONLY: do not create, edit, patch, or move any note, unless the arguments carry --save=<path>. Then write the table to the note at that path using silica_write_note (create it if missing, overwrite if present): the table is the entire body, plus a one-line title.
