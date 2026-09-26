# Backend

Python package `iknownothing`: HTTP API, Course Store, AI Client, Ingestion, and
Tutor (see [arc42 chapter 5](../docs/arc42/05-building-block-view.adoc)).

## Development

The backend runs in Docker (see the [README](../README.md)); in the
development setup it reloads on every change under `src/`. The tests
run in the container:

```sh
docker compose exec backend pytest
```

Ingestion logs the token usage of every request; `course add` prints
the totals per model at the end.

## API

Every request except listing and choosing users is served for the
user in the cookie `ikn_user`:

```sh
curl -c cookies -H 'content-type: application/json' \
    -d '{"name": "alice"}' localhost:8000/api/user
curl -b cookies localhost:8000/api/courses/control-theory
curl -b cookies -N localhost:8000/api/courses/control-theory/chat \
    -H 'content-type: application/json' \
    -d '{"topic": null, "transcript": [{"role": "user", "content": "Where do I stand?"}]}'
```

Open chats are stored per course and topic; ending a topic-level session finalizes it in the backend process.

| Endpoint | |
|---|---|
| `GET /api/users` | all users |
| `GET /api/user` | the chosen user |
| `POST /api/user` | chooses a user; sets the cookie |
| `GET /api/courses` | the user's courses |
| `GET /api/courses/<course>` | topics in priority order, with their Markdown files and token usage; token usage of the course-level chats. Usage: `input` (cached included), `cached`, `output` tokens, and approximate `eur` |
| `GET /api/courses/<course>/files/<path>` | one Markdown file |
| `POST /api/courses/<course>/chat` | stores the chat with the reply; streams the reply as Server-Sent Events: `text`, `cheatsheet`, `task`, then `usage` with the reply's tokens and `messages` to append to the transcript, or `error`; a comment every 10 s while the model thinks |
| `GET /api/courses/<course>/chat?topic=<slug>` | the open chat of a topic, or without `topic` of the course: `transcript` and `usage` |
| `DELETE /api/courses/<course>/chat?topic=<slug>` | ends the open chat; for a topic, updates `progress.md` in the background |
