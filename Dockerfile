FROM node:24-bookworm-slim AS frontend
WORKDIR /ui
COPY frontend/package*.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

FROM python:3.11-slim-bookworm
RUN apt-get update && apt-get install -y --no-install-recommends tesseract-ocr tesseract-ocr-eng tesseract-ocr-por && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY backend/requirements* backend/
RUN pip install --no-cache-dir -r backend/requirements.lock -r backend/requirements-postgres.txt
COPY backend/ backend/
COPY fixtures/ fixtures/
COPY --from=frontend /ui/dist frontend/dist
RUN useradd --create-home appuser && mkdir -p storage && chown -R appuser:appuser /app
USER appuser
ENV PYTHONPATH=/app/backend PYTHONUNBUFFERED=1
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
