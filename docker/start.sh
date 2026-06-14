#!/bin/sh
cd /app
gunicorn --bind 127.0.0.1:5000 --workers 2 --timeout 60 app:app &
nginx -g 'daemon off;'
