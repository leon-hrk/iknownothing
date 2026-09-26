FROM node:24-slim AS frontend
WORKDIR /frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

FROM python:3.12-slim AS base
WORKDIR /app
COPY backend/pyproject.toml backend/README.md ./
COPY backend/src ./src
RUN pip install --no-cache-dir .
ENV IKN_DATA_DIR=/data IKN_COURSES_DIR=/courses PYTHONUNBUFFERED=1
EXPOSE 8000

# docker-compose.dev.yml: the source is mounted and reloaded on change
FROM base AS dev
RUN pip install --no-cache-dir '.[dev]'
ENV PYTHONPATH=/app/src PYTEST_ADDOPTS="-p no:cacheprovider"
CMD ["uvicorn", "iknownothing.api:app", "--host", "0.0.0.0", "--port", "8000", "--reload", "--reload-dir", "/app/src"]

FROM base
COPY --from=frontend /frontend/dist ./frontend
ENV IKN_FRONTEND_DIR=/app/frontend
CMD ["uvicorn", "iknownothing.api:app", "--host", "0.0.0.0", "--port", "8000"]
