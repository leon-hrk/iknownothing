# iknownothing

A self-hosted, AI-powered exam preparation tutor. Architecture and
scope: [docs/arc42](docs/arc42/README.md). Development:
[backend](backend/README.md), [frontend](frontend/README.md).

## Running

Needs Docker with Compose, nothing else.

```sh
cp .env.example .env    # fill in the API key
chmod 600 .env
mkdir -p data courses
docker compose up -d --build
```

The app is on http://localhost:8000. It has no login: every user
picks themselves from a list, so it must stay on localhost or behind
a reverse proxy that authenticates.

## Users and courses

```sh
docker compose exec backend iknownothing user add alice
docker compose exec backend iknownothing user remove alice    # deletes data/alice/ with her courses
```

The operator hands a course to a user. The material goes into
`courses/<course>/`:

```
courses/control-theory/
├── notes.md            remarks on the course, e.g. what the exam covers
├── exams/*.pdf         past exams and solution proposals
└── exercises/*.pdf     exercise sheets and solutions
```

```sh
docker compose exec backend iknownothing course add alice control-theory
docker compose exec backend iknownothing course add bob control-theory --from alice
docker compose exec backend iknownothing course ingest alice control-theory   # resumes a failed ingestion
docker compose exec backend iknownothing course remove alice control-theory
```

`add` ingests the course, which takes a few minutes and costs one
large request. `add --from` copies alice's ingested course without her
cheatsheet and progress, at no cost.

## Development

With this line in `.env`, `docker compose up -d --build` starts the
development setup instead: the backend reloads on source changes, and
Vite serves the frontend with hot reload on http://localhost:5173.

```sh
COMPOSE_FILE=docker-compose.yml:docker-compose.dev.yml
```
