#!/bin/sh
set -e

python manage.py migrate

gunicorn config.wsgi:application --bind 127.0.0.1:8000 --workers "${GUNICORN_WORKERS:-3}" &

if [ "${RUN_CELERY_IN_APP:-0}" = "1" ]; then
  celery -A config worker -l info &
fi

exec nginx -g 'daemon off;'
