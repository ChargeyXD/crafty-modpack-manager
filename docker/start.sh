#!/bin/sh
set -e
cd /app
gunicorn --bind 127.0.0.1:5000 --workers 2 --timeout 60 --log-level info app:app &
exec nginx -g 'daemon off;'
