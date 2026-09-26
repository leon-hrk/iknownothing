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

Topic-level chats are finalized in the backend process.

| Endpoint | |
|---|---|
| `GET /api/users` | all users |
| `GET /api/user` | the chosen user |
| `POST /api/user` | chooses a user; sets the cookie |
| `GET /api/courses` | the user's courses |
| `GET /api/courses/<course>` | topics in priority order, with their Markdown files |
| `GET /api/courses/<course>/files/<path>` | one Markdown file |
| `POST /api/courses/<course>/chat` | streams the reply as Server-Sent Events: `text`, `cheatsheet`, `task`, then `messages` to append to the transcript, or `error`; a comment every 10 s while the model thinks |
| `POST /api/courses/<course>/topics/<slug>/finalize` | ends a topic-level chat; updates `progress.md` in the background |
