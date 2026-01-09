FROM python:3.13-slim

# Set environment variables
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV PORT=8080

# Install system dependencies (for python-magic, pillow, etc.)
RUN apt-get update && apt-get install -y --no-install-recommends \
    libmagic1 \
    poppler-utils \
    && rm -rf /var/lib/apt/lists/*

# Set work directory
WORKDIR /app

# Copy dependency files and source code
COPY pyproject.toml ./
COPY src/ ./src/

# Install Python dependencies
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir .

# Create uploads directory
RUN mkdir -p /app/uploads

# Expose port
EXPOSE 8080

# Run the application
CMD ["uvicorn", "docparser.api.main:app", "--host", "0.0.0.0", "--port", "8080"]
