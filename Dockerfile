FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

ENV PYTHONPATH=/app
ENV PYTHONUNBUFFERED=1

ENTRYPOINT ["/bin/bash", "-c"]
CMD ["gunicorn --bind 0.0.0.0:${PORT:-8080} --workers 1 --timeout 300 src.api:app"]
