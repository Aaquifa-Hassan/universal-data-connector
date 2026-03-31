FROM python:3.11-slim

WORKDIR /gateway

# Install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy source
COPY app/ ./app/

# .env is NOT copied — provide credentials via Docker secrets or env vars at runtime
EXPOSE 8080

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8080"]
