#!/usr/bin/env bash
# Start the mock CRM & Support API server on port 8001
# Run from the project root: bash mock_api_server/start.sh

cd "$(dirname "$0")/.." || exit 1
uvicorn mock_api_server.server:app --port 8001 --reload
