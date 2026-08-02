#!/usr/bin/bash

echo "==> Running migrations"
uv run alembic upgrade head

echo "==> Starting fedikeysmash"
uv run main.py
