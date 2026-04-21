FROM python:3.11-slim

WORKDIR /app

# Install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy source code
COPY . .

# Set Python path so src/ modules can import each other
ENV PYTHONPATH=/app/src
ENV PYTHONUNBUFFERED=1

# Expose port
EXPOSE 8080

# Start gunicorn
CMD gunicorn src.api:app --bind 0.0.0.0:$PORT --workers 1 --timeout 300 --chdir /app
