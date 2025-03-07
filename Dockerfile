# Use Python 3.9 from Docker Hub
FROM python:3.12-slim

# Set working directory
WORKDIR /app

# Install system dependencies with apt-key and repository updates
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
    gnupg2 \
    && apt-key update \
    && apt-get update \
    && apt-get install -y --no-install-recommends \
    ffmpeg \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements file
COPY requirements.txt .

# Install Python dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY app/ /app/

# Create directories for temporary files
RUN mkdir -p /app/temp/output

# Set environment variables
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    TEMP_DIR=/app/temp \
    OUTPUT_DIR=/app/temp/output

# Expose the port
EXPOSE 8000

# Run the application
# CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
CMD ["sh", "-c", "uvicorn main:app --host 0.0.0.0 --port ${PORT:-8000}"]