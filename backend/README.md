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

Ingestion logs the token usage of every request; `course add`,
`course update`, and `course ingest` print the totals per model at the
end.

## API

Every request except listing and choosing users is served for the
user in the cookie `ikn_user`:

```sh
curl -c cookies -H 'content-type: application/json' \
    -d '{"name": "alice"}' localhost:8000/api/user
curl -b cookies localhost:8000/api/courses/control-theory
curl -b cookies -N localhost:8000/api/courses/control-theory/chat \
    -H 'content-type: application/json' \
    -d '{"topic": "laplace", "transcript": [{"role": "user", "content": "Bring mir das Thema bei"}]}'
```

Open chats are stored per topic; a chat records each completed step in the topic's `progress.json`. Ingestions started over the API run as background tasks of the backend process, at most one per course.

| Endpoint | |
|---|---|
| `GET /api/users` | all users |
| `GET /api/user` | the chosen user |
| `POST /api/user` | chooses a user; sets the cookie |
| `GET /api/courses` | the user's courses: `name`, `status` (`ready` or `not ingested`), `ingestion` (the step of a running ingestion, or null), `error` (why the last ingestion failed, or null) |
| `POST /api/courses` | multipart `name` (lowercase letters, digits, hyphens, underscores), `notes`, `exams` and `exercises` PDFs: creates the course and starts its ingestion; 409 if it exists, 422 for an invalid name, no PDFs, or a file that is not a PDF |
| `POST /api/courses/<course>/files` | multipart `notes`, `exams`, `exercises`: adds the PDFs the course lacks, replaces its notes, and starts the ingestion; 422 for a changed PDF of the same name, 409 while it is being ingested |
| `POST /api/courses/<course>/ingestion` | starts the ingestion again, from the steps whose results are missing; 409 while one runs |
| `DELETE /api/courses/<course>` | deletes the course with everything in it; 409 while it is being ingested |
| `GET /api/courses/<course>` | topics in priority order, with their score (percentage of tasks done, `null` without tasks), Markdown files, `progress.json`, and token usage. Usage: `input` (cached included), `cached`, `output` tokens, and approximate `eur` |
| `GET /api/courses/<course>/files/<path>` | one course file |
| `POST /api/courses/<course>/chat` | stores the chat with the reply; streams the reply as Server-Sent Events: `text`, `cheatsheet`, `task`, `step`, then `usage` with the reply's tokens and `messages` to append to the transcript, or `error`; a comment every 10 s while the model thinks |
| `GET /api/courses/<course>/chat?topic=<slug>` | the open chat of a topic: `transcript` and `usage` |
| `DELETE /api/courses/<course>/chat?topic=<slug>` | ends the open chat |
