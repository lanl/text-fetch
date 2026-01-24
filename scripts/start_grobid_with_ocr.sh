#!/usr/bin/env bash
#
# Start GROBID service with OCR support in Docker for PDF processing.
# This variant includes Tesseract OCR for processing scanned PDFs.
#
# Usage: ./scripts/start_grobid_with_ocr.sh
#
# Note: The -full image is ~5GB (vs ~2GB for standard).
# First startup may be slow while downloading models.
#
# Use this when processing scanned/image-only PDFs.
# For modern PDFs with embedded text, the standard start_grobid.sh is faster.
#

set -euo pipefail

GROBID_IMAGE="grobid/grobid:0.8.2-full"
GROBID_NAME="grobid"
GROBID_PORT=8070
GROBID_ADMIN_PORT=8071

echo "Starting GROBID service with OCR support..."
echo "  Using image: $GROBID_IMAGE"
echo "  (This image includes Tesseract OCR for scanned PDFs)"
echo ""

# Remove existing container if present (ignore errors if it doesn't exist)
docker rm -f "$GROBID_NAME" 2>/dev/null || true

# Start GROBID in background
# Note: The -full image may take longer to start on first run
docker run -d \
  --name "$GROBID_NAME" \
  --restart unless-stopped \
  --init \
  --ulimit core=0 \
  -p "${GROBID_PORT}:8070" \
  -p "${GROBID_ADMIN_PORT}:8071" \
  "$GROBID_IMAGE"

echo "Waiting for GROBID to be ready..."
echo "(First startup may take 60+ seconds for the -full image)"

# Wait for GROBID to be responsive (can take longer for -full image)
max_attempts=120
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
echo "GROBID with OCR is ready!"
echo "  Service URL: http://localhost:${GROBID_PORT}"
echo "  Admin URL:   http://localhost:${GROBID_ADMIN_PORT}"
echo ""
echo "OCR is enabled. Use --ocr flag with text-fetch pdf commands:"
echo "  text-fetch pdf process ./pdfs --out ./output --ocr"
echo ""
echo "To stop GROBID: docker stop $GROBID_NAME"
echo "To view logs:   docker logs $GROBID_NAME"
