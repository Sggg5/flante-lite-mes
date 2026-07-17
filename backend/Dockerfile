FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

COPY pyproject.toml alembic.ini ./
COPY alembic ./alembic
COPY app ./app

RUN pip install --upgrade pip && pip install .

EXPOSE 8000

CMD ["sh", "-c", "alembic upgrade head && python -m app.scripts.init_db && uvicorn app.main:app --host 0.0.0.0 --port 8000"]
