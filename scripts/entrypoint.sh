#!/bin/bash
set -e

# Initialize database if needed
# We check if the data directory exists and is writable
echo "Starting Universal Data Connector..."

if [ ! -f "data/student_data.db" ]; then
    echo "Database file not found."
    if [ -f "data/project_data.csv" ]; then
        echo "Found seed data CSV. Initializing database..."
        python3 scripts/import_csv.py
    else
        echo "Warning: No seed data found at data/project_data.csv. Starting with empty database."
    fi
else
    echo "Database already exists."
fi

# Start the application
echo "Starting Uvicorn..."
exec uvicorn app.main:app --host 0.0.0.0 --port 8000
