FROM python:3.12-slim

# Install system dependencies required for cryptography and networking tools
RUN apt-get update && apt-get install -y \
    build-essential \
    libffi-dev \
    python3-dev \
    iputils-ping \
    net-tools \
    && rm -rf /var/lib/apt/lists/*

# Set working directory
WORKDIR /app

COPY requirements.txt .

# Install Python dependencies
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Install the application in editable mode
RUN pip install -e .

# Set environment variable for storage root
ENV SHADOWBOX_STORAGE_ROOT=/shdwbx/data

# Create the data directory
RUN mkdir -p /shdwbx/data

# Expose the port used by ShadowBox
EXPOSE 9999

# Define a volume for persistent data
VOLUME ["/shdwbx/data"]

# Entry point to run the CLI app
ENTRYPOINT ["python", "-m", "shadowbox.frontend.cli.app"]
