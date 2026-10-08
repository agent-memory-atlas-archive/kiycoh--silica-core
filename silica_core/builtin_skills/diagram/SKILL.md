---
name: diagram
description: Mermaid diagram of a note, folder, or topic
argument-hint: "<note|folder|topic> [--save=<path>]"
metadata:
  internal: true
---
Diagram from the vault: $ARGUMENTS

Resolve the target: it may be a note (path or title), a folder (list and skim its notes), or a general topic (search the vault, then read the top matches).
Pick the form from the relation the reader has to follow, not from the topic:
- how a mechanism works, a cause and its effects, a route: `flowchart`, the parts as nodes and the actions as labelled arrows in the causal direction
- states and what moves between them: `stateDiagram-v2`
- who sends what to whom, in order: `sequenceDiagram`
- a hierarchy or a taxonomy: `mindmap`, or a top-down `flowchart` with no cross links
- events in time: `timeline`, with only the events the notes give
- items compared on attributes, or numbers to compare: a Markdown table instead of a diagram
- a physical layout (an organ, a device): the note's own figure embed `![[file.png]]`, when it has one
Keep it to at most 9 nodes; when there are more, draw the part the request is about. Every arrow carries a verb, and all arrows in one diagram mean the same kind of thing. Name each node with the words the notes use, and draw only what you read in them.
Output in chat: a one-line caption that says what the diagram shows, then a single fenced ```mermaid block (or the table, or the embed), then one question the reader can answer only by using it.
READ-ONLY: do not create, edit, patch, or move any note, unless the arguments carry --save=<path>. Then write the diagram to the note at that path using silica_write_note (create it if missing, overwrite if present): the diagram is the entire body, plus a one-line title.
