FROM python:3.13-alpine

WORKDIR /app

RUN apk add --no-cache postgresql17 postgresql17-dev gcc
RUN pip3 install --upgrade uv

COPY pyproject.toml .
COPY uv.lock .

RUN uv sync

COPY docker-entrypoint.sh .
COPY main.py .
COPY auth.py .
COPY database.py .
COPY logger.py .
COPY user_prefs.py .

ENTRYPOINT ["bash", "docker-entrypoint.sh"]
