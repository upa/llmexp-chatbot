#!/bin/sh

set -e

DB_PATH="/app/data/sqlite.db"
SCHEMA_PATH="/app/scheme.sql"

if [ ! -f "$DB_PATH" ]; then
  echo "Database not found at $DB_PATH. Initializing..."
  if [ -f "$SCHEMA_PATH" ]; then
    sqlite3 "$DB_PATH" < "$SCHEMA_PATH"
    echo "Database initialized."
  else
    echo "Error: Schema file not found at $SCHEMA_PATH. Cannot initialize database."
    exit 1
  fi
else
  echo "Database found at $DB_PATH."
fi

exec "$@"
