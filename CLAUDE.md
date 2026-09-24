# CLAUDE.md

## Documentation: current state only

**Documents describe how things are, not how we got there.** Code,
comments, and project docs state the present design. They do not carry
decision logs, rejected alternatives, or "we chose X over Y because…".

Concretely, do not add:

- "Resolved Decisions", "Design Rationale", "Trade-offs", or
  "Alternatives Considered" sections
- Comments explaining why a previous approach was replaced
- Changelog-style prose in docs ("previously X, now Y")
- Dates, PR numbers, or incident references used as justification

Stating a **constraint** is not the same as justifying a decision.
"Any provider must support multimodal document input" is current
state and belongs in the doc; "we picked Claude vision over marker
because of Docker image size" is a decision and belongs in arc42
chapter 9.

**Rationale lives in arc42 chapter 9 — and nowhere else.** Only
decisions with lasting structural impact get an entry there. Most
decisions get none: they are simply visible in the code.

## Commit messages

Short and factual. A subject line, plus bullet points if more than one
thing happened. Say *what* changed. Do not explain, justify, or
summarise the discussion that led to it.

```
Add vision, init arc42

- VISION.md: product vision, ingestion pipeline, UI sketch
- docs/arc42: chapter scaffold (AsciiDoc + PlantUML)
```

- Imperative mood in the subject line, no trailing period.
- Bullets name the substance of the change, not every file touched.
  Housekeeping (`.gitignore`, formatting, renames) gets no line.
- No essays, no "Context/Decision/Consequences" blocks, no restating
  the diff in prose.
- No trailers. In particular no `Co-Authored-By` for AI assistance —
  the commit is the author's work regardless of what helped write it.
- If a change feels like it needs a long body, it needs an arc42
  chapter 9 entry instead.
