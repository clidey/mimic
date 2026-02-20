#!/usr/bin/env bash
set -euo pipefail

CONTAINER="whodb-postgres"
DB="whodb"
USER="whodb"
SQL_PATH="/opt/whodb/sample-data.sql"

docker exec -i "$CONTAINER" psql -U "$USER" -d "$DB" < "$SQL_PATH"
