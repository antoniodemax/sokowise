#!/bin/sh
# Container start: apply migrations, then serve (docs/OPERATIONS.md).
#
# Hosts without a separate pre-deploy step (Render free) run this as the Docker command.
# The readiness check (/health/ready) refuses traffic while the schema is behind the shipped
# head, so a failed migration keeps the previous version serving. With a single instance the
# ordering guarantee is the same as Railway's preDeployCommand.
set -eu
alembic upgrade head
exec uvicorn app.main:app --host "${API_HOST:-0.0.0.0}" --port "${API_PORT:-8000}"
