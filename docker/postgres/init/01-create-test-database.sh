#!/bin/sh
# Runs once when the postgres volume is first initialised (docker-entrypoint-initdb.d).
# Creates the database the backend test suite uses (TEST_DATABASE_URL), owned by the app role.
set -eu
TEST_DB="${POSTGRES_DB}_test"
psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" <<SQL
CREATE DATABASE "${TEST_DB}" OWNER "${POSTGRES_USER}";
SQL
