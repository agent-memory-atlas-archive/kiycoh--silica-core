---
name: compare
description: comparison table of notes/concepts; surfaces contradictions
argument-hint: '"<A>" "<B>" [...]'
metadata:
  internal: true
---
Compare from the vault: $ARGUMENTS

Each subject is a note (path or title) or a concept: locate and read the matching note(s) for each. Output in chat: a comparison table (one column per subject, dimensions as rows), then a short similarities/differences rundown. If any involved note carries `contested: true`, or the notes contradict each other, call that out explicitly. A contradiction the reader confirms is worth recording: offer to run silica_flag_note on the note that is wrong, and only run it once they say so.
READ-ONLY apart from that flag: do not create, edit, patch, or move any note.
