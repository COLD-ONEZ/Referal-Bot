# ════════════════════════════════════════════════
#  Referral Reward Bot — Dockerfile
#  Python 3.11 slim image for minimal footprint
# ════════════════════════════════════════════════

FROM python:3.11-slim

# Set working directory
WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    gcc \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements first (layer caching)
COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir -r requirements.txt

# Copy project files
COPY . .

# Create non-root user for security
RUN useradd -m -u 1000 botuser && chown -R botuser:botuser /app
USER botuser

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=10s --retries=3 \
    CMD python -c "import asyncio; asyncio.run(__import__('database.connection', fromlist=['connect']).connect())" || exit 1

# Entry point
CMD ["python", "main.py"]
