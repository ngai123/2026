# Use Python 3.13 as per pyproject.toml
FROM python:3.13-slim

# Set environment variables
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PORT=7860 \
    MCP_PORT=8766 \
    MCP_SERVER_URL=http://0.0.0.0:8766/sse \
    DASHBOARD_URL=http://0.0.0.0:7860 \
    DASHBOARD_AI_URL=http://0.0.0.0:7860/api/ai_event \
    HEADLESS=true

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    lsof \
    && rm -rf /var/lib/apt/lists/*

# Set work directory
WORKDIR /app

# Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy project files
COPY . .

# Expose ports
EXPOSE 8765 8766

# Start the application
# main.py orchestrates the MCP server, dashboard, and the swarm logic.
CMD ["python", "main.py"]
