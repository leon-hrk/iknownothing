# CLAUDE.md

## Project

iknownothing is a self-hosted, AI-powered exam preparation tutor:
users upload course materials, the agent distills them into
structured topics and tutors them through to exam readiness,
keeping a cheatsheet and per-topic progress along the way. Scope,
requirements, and quality goals are in
[arc42 chapter 1](docs/arc42/01-introduction-and-goals.adoc).

## Architecture spec drives the code

The architecture is specified in [docs/arc42](docs/arc42/README.md).
Code is written against that spec — read the relevant chapters before
implementing, and keep implementation and spec consistent.

The spec is not frozen. When development shows that something in it
is wrong, incomplete, or impractical, change the spec in the same
branch as the code. Code and arc42 never disagree on `main`.

## Branching

- All work happens on a branch off `main`: `feature/<name>` or
  `fix/<name>` (`docs/<name>` for documentation-only changes).
- No direct commits to `main`.
- A branch lands on `main` as **one squashed commit**. Its message
  follows the commit rules below.

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
