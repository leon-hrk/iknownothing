# Backend

Python package `iknownothing`: Course Store, AI Client, and Ingestion
(see [arc42 chapter 5](../docs/arc42/05-building-block-view.adoc)).

## Setup

```sh
cd backend
python3 -m venv .venv
.venv/bin/pip install -e '.[dev]'
.venv/bin/pytest
```

## Dev CLI

`ikn-dev` creates and ingests courses from local files, without frontend
and database. It is a development tool, not part of the product.

Configuration comes from the environment (see `../.env.example`):

```sh
set -a; . ../.env; set +a
export IKN_DATA_DIR="$PWD/../data"
```

```sh
.venv/bin/ikn-dev course create alice control-theory \
    --notes notes.md \
    --exams exams/*.pdf \
    --exercises exercises/*.pdf

.venv/bin/ikn-dev course ingest alice control-theory
```

The course lands in `$IKN_DATA_DIR/<user>/<course>/`. `ingest` can be
rerun after a failure; it skips the topic extraction once its result
exists.
Token usage per request is logged to stderr, totals per model are
printed at the end.
