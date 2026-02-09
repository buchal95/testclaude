FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

ENV DATABASE_PATH=/app/data/networking.db
RUN mkdir -p /app/data

EXPOSE 8080

CMD ["/bin/sh", "-c", "gunicorn --bind 0.0.0.0:${PORT:-8080} networking_tool.wsgi:app"]
