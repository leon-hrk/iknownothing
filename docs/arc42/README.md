# Architecture (arc42)

Architecture documentation following the [arc42](https://arc42.org)
template, written in AsciiDoc. `arc42.adoc` is the document;
`NN-*.adoc` are its chapters, pulled in via `include::`.

| # | Chapter |
|---|---|
| 1 | [Introduction and Goals](01-introduction-and-goals.adoc) |
| 2 | [Architecture Constraints](02-architecture-constraints.adoc) |
| 3 | [Context and Scope](03-context-and-scope.adoc) |
| 4 | [Solution Strategy](04-solution-strategy.adoc) |
| 5 | [Building Block View](05-building-block-view.adoc) |
| 6 | [Runtime View](06-runtime-view.adoc) |
| 7 | [Deployment View](07-deployment-view.adoc) |
| 8 | [Cross-cutting Concepts](08-crosscutting-concepts.adoc) |
| 9 | [Architecture Decisions](09-architecture-decisions.adoc) |
| 10 | [Quality Requirements](10-quality-requirements.adoc) |
| 11 | [Risks and Technical Debt](11-risks-and-technical-debt.adoc) |
| 12 | [Glossary](12-glossary.adoc) |

## Building

The rendered document is optional - the chapter files are readable as
plain text. Only set this up if you want the built output or need
diagrams rendered.

```sh
gem install asciidoctor asciidoctor-diagram asciidoctor-pdf
# PlantUML additionally needs a JRE and Graphviz:
#   apt install default-jre graphviz

asciidoctor -r asciidoctor-diagram docs/arc42/arc42.adoc       # HTML
asciidoctor-pdf -r asciidoctor-diagram docs/arc42/arc42.adoc   # PDF
```

Output and the diagram cache land in `docs/arc42/build/`, which is
git-ignored. Generated images are never committed - they are rebuilt
from source.

## Diagrams

PlantUML, rendered at build time. Sources live in `diagrams/` and are
referenced from a chapter:

```asciidoc
[plantuml, target=ingestion-pipeline, format=svg]
....
include::diagrams/ingestion-pipeline.puml[]
....
```

Short one-off diagrams can be written inline in the chapter instead of
getting their own file.

Note that GitHub renders `.adoc` files but does **not** resolve
`include::` or render PlantUML in the web view. Browsing the chapters
on GitHub shows them individually, with diagram blocks as source text.
Build locally to see the whole document.

## Conventions

- **Do not duplicate [VISION.md](../../VISION.md).** Vision owns the
  product intent; arc42 owns how it is built. Link, don't copy.
- **Chapter 9 is the only place in the repo where rationale lives**
  (see [CLAUDE.md](../../CLAUDE.md)). Everywhere else documents the
  current state; the argument for a decision goes in the commit that
  implements it, and only decisions with lasting structural impact
  are promoted into chapter 9.
- Open questions stay in VISION.md until they are answered. Answering
  one means writing the result into the relevant chapter here and
  removing it there.
- Not every chapter needs content. An empty chapter is a valid state
  and better than filler.
