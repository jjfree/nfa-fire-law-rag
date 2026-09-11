FROM python:3.12-slim
WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
COPY pyproject.toml README.md ./
COPY app ./app
# This image backs the optional PostgreSQL/pgvector compose stack. Native
# SQLite users do not need Docker or this image.
RUN pip install --no-cache-dir ".[postgres]"
CMD ["uvicorn", "app.api:app", "--host", "0.0.0.0", "--port", "8000"]
