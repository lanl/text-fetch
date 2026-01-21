#!/usr/bin/env bash
#
# Start GROBID service in Docker for PDF processing.
# Usage: ./scripts/start_grobid.sh
#

set -euo pipefail

GROBID_IMAGE="grobid/grobid:0.8.2-crf"
GROBID_NAME="grobid"
GROBID_PORT=8070
GROBID_ADMIN_PORT=8071

echo "Starting GROBID service..."

# Remove existing container if present (ignore errors if it doesn't exist)
docker rm -f "$GROBID_NAME" 2>/dev/null || true

# Start GROBID in background
docker run -d \
  --name "$GROBID_NAME" \
  --restart unless-stopped \
  --init \
  --ulimit core=0 \
  -p "${GROBID_PORT}:8070" \
  -p "${GROBID_ADMIN_PORT}:8071" \
  "$GROBID_IMAGE"

echo "Waiting for GROBID to be ready..."

# Wait for GROBID to be responsive (can take 30+ seconds on first startup)
max_attempts=60
attempt=0
until curl -sS "http://localhost:${GROBID_PORT}/api/isalive" 2>/dev/null; do
  attempt=$((attempt + 1))
  if [ $attempt -ge $max_attempts ]; then
    echo "ERROR: GROBID did not start within ${max_attempts} seconds"
    docker logs "$GROBID_NAME"
    exit 1
  fi
  echo "  Waiting... ($attempt/${max_attempts})"
  sleep 1
done

echo ""
echo "GROBID is ready!"
echo "  Service URL: http://localhost:${GROBID_PORT}"
echo "  Admin URL:   http://localhost:${GROBID_ADMIN_PORT}"
echo ""
echo "To stop GROBID: docker stop $GROBID_NAME"
echo "To view logs:   docker logs $GROBID_NAME"
