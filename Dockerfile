
# Use python 3.11 slim image
FROM python:3.11-slim

# Set environment variables
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    APP_HOME=/app

# Create app directory
WORKDIR $APP_HOME

# Install system dependencies (if needed, e.g. for building python packages)
# RUN apt-get update && apt-get install -y gcc && rm -rf /var/lib/apt/lists/*

# Install python dependencies
COPY requirements.txt .
RUN pip install --upgrade pip && \
    pip install -r requirements.txt

# Create a non-root user and group
RUN groupadd -r appuser && useradd -r -g appuser appuser

# Copy application code
COPY . .

# Set permissions for the data directory so the appuser can write to the database
RUN mkdir -p data && chown -R appuser:appuser data

# Switch to non-root user
USER appuser

# Expose port
EXPOSE 8000

# Copy and set entrypoint script
COPY scripts/entrypoint.sh /app/scripts/entrypoint.sh

# Entrypoint will stand up the service
ENTRYPOINT ["/bin/bash", "/app/scripts/entrypoint.sh"]
