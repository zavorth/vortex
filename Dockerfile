FROM python:3.11-slim

WORKDIR /app

# Install system dependencies for Playwright
RUN apt-get update && apt-get install -y --no-install-recommends \
    wget \
    gnupg \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements and install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Install Playwright Chromium
RUN python -m playwright install chromium

# Copy application code
COPY . .

# Create necessary directories
RUN mkdir -p saved_cookies bin

# Expose port
EXPOSE 8080

# Run the application
CMD ["python", "app.py"]
