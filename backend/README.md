# Backend

Python package `iknownothing`: HTTP API, Course Store, AI Client, Ingestion, and
Tutor (see [arc42 chapter 5](../docs/arc42/05-building-block-view.adoc)).

## Setup

```sh
cd backend
python3 -m venv .venv
.venv/bin/pip install -e '.[dev]'
.venv/bin/pytest
```

## Dev CLI

`ikn-dev` creates and ingests courses from local files and runs
course-level and topic-level chats in the terminal, without frontend and database. It is a development tool, not part of the product.

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

```sh
.venv/bin/ikn-dev chat alice control-theory
.venv/bin/ikn-dev chat alice control-theory nyquist-stability
```

`chat` opens a chat on an ingested course: course-level without a
topic, topic-level with a topic's slug from `topics.json`. The tutor
writes `cheatsheet.md` during the chat. An empty line or Ctrl-D ends
it; a topic-level chat then finalizes the topic's `progress.md`.

Token usage per request is logged to stderr, totals per model are
printed at the end.

## API

The HTTP API runs with uvicorn on the same data directory. Until
accounts exist, every request is served for the user named by
`IKN_USER`; topic-level chats are finalized in the backend process.
With `IKN_FRONTEND_DIR` set to the built frontend (`../frontend/dist`),
the backend serves it too.

```sh
export IKN_USER=alice
.venv/bin/uvicorn iknownothing.api:app --port 8000
```

```sh
curl localhost:8000/api/courses/control-theory
curl -N localhost:8000/api/courses/control-theory/chat \
    -H 'content-type: application/json' \
    -d '{"topic": null, "transcript": [{"role": "user", "content": "Where do I stand?"}]}'
```

| Endpoint | |
|---|---|
| `GET /api/courses` | the user's courses |
| `GET /api/courses/<course>` | topics in priority order, with their Markdown files |
| `GET /api/courses/<course>/files/<path>` | one Markdown file |
| `POST /api/courses/<course>/chat` | streams the reply as Server-Sent Events: `text`, `cheatsheet`, `task`, then `messages` to append to the transcript, or `error`; a comment every 10 s while the model thinks |
| `POST /api/courses/<course>/topics/<slug>/finalize` | ends a topic-level chat; updates `progress.md` in the background |
