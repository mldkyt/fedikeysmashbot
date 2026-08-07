FROM python:3.13-alpine

WORKDIR /app

RUN apk add --no-cache postgresql17 postgresql17-dev gcc bash
RUN pip3 install --upgrade uv

COPY pyproject.toml .
COPY uv.lock .

RUN uv sync

COPY alembic/ alembic/.
COPY alembic.ini .
COPY docker-entrypoint.sh .
COPY main.py .
COPY auth.py .
COPY database.py .
COPY logger.py .
COPY user_prefs.py .

STOPSIGNAL SIGINT

ENTRYPOINT ["bash", "docker-entrypoint.sh"]
