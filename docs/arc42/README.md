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
plain text. Only build it if you want the rendered output or need
diagrams rendered.

The build runs [Asciidoctor](https://asciidoctor.org) with
Asciidoctor Diagram in its official Docker image and needs nothing
but Docker. From the repository root:

```sh
docker run --rm -u "$(id -u):$(id -g)" -e HOME=/tmp \
  -v "$PWD":/documents -w /documents/docs/arc42 \
  asciidoctor/docker-asciidoctor sh -c '
    asciidoctor     -r asciidoctor-diagram -D build arc42.adoc &&
    asciidoctor-pdf -r asciidoctor-diagram -D build arc42.adoc'
```

This writes `docs/arc42/build/arc42.html` and
`docs/arc42/build/arc42.pdf`.

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

- **arc42 is the specification.** Product scope and requirements are
  chapter 1.
- **Chapter 9 is the only place in the repo where rationale lives**
  (see [CLAUDE.md](../../CLAUDE.md)). Everywhere else documents the
  current state, commit messages included. Only decisions with
  lasting structural impact get a chapter 9 entry; all others are
  simply visible in the code.
- Not every chapter needs content. An empty chapter is a valid state
  and better than filler.
