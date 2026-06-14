FROM python:3.12-slim

# Install nginx and tini (clean PID-1 process manager)
RUN apt-get update \
 && apt-get install -y --no-install-recommends nginx tini curl \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY backend/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY backend/app.py .
COPY frontend/ /usr/share/nginx/html/
COPY docker/nginx.conf /etc/nginx/sites-available/default
COPY docker/start.sh /start.sh
RUN chmod +x /start.sh

HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
  CMD curl -sf http://localhost:7800/health || exit 1

EXPOSE 7800
ENTRYPOINT ["/usr/bin/tini", "--"]
CMD ["/start.sh"]
