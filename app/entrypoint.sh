#!/bin/bash
set -e

echo "========================================="
echo "  壹米云相册 v3.0.0"
echo "========================================="
echo "数据目录: ${YIMI_DATA_DIR:-/data/photos}"
echo "端口: ${PORT:-8080}"

mkdir -p "${YIMI_DATA_DIR:-/data/photos}"          "${YIMI_DATA_DIR:-/data/photos}/.thumbs"          "${YIMI_DATA_DIR:-/data/photos}/.trash"          "${YIMI_DATA_DIR:-/data/photos}/.faces"          "${YIMI_DATA_DIR:-/data/photos}/.config"

exec gunicorn \
    --bind "0.0.0.0:${PORT:-8080}" \
    --workers "${GUNICORN_WORKERS:-2}" \
    --threads "${GUNICORN_THREADS:-4}" \
    --timeout 120 \
    --graceful-timeout 30 \
    --max-requests 1000 \
    --max-requests-jitter 50 \
    --access-logfile - \
    --error-logfile - \
    --log-level info \
    "app:create_app()"

