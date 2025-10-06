#!/bin/bash
set -e

# Detect OS
if [[ "$OSTYPE" == "linux-gnu"* ]]; then
    OS="linux"
elif [[ "$OSTYPE" == "darwin"* ]]; then
    OS="mac"
elif [[ "$OSTYPE" == "msys" ]] || [[ "$OSTYPE" == "cygwin" ]]; then
    OS="windows"
else
    echo "Unsupported OS: $OSTYPE"
    exit 1
fi

# Check Python version
PYTHON_VERSION=$(python3 --version 2>&1 | grep -Po '(?<=Python )\d+\.\d+')
REQUIRED_VERSION="3.9"
if (( $(echo "$PYTHON_VERSION < $REQUIRED_VERSION" | bc -l) )); then
    echo "Python $REQUIRED_VERSION or higher is required (found $PYTHON_VERSION)"
    exit 1
fi

# Create virtual environment if it doesn't exist
if [ ! -d "venv" ]; then
    python3 -m venv venv
fi

# Activate virtual environment
if [ "$OS" == "windows" ]; then
    source venv/Scripts/activate
else
    source venv/bin/activate
fi

# Upgrade pip and install dependencies
pip install --upgrade pip
pip install -r requirements.txt

# Install pre-commit hooks
pre-commit install
pre-commit run --all-files || true

# Create .env file if it doesn't exist
if [ ! -f ".env" ]; then
    cat > .env << 'ENVEOF'
DEBUG=True
LOG_LEVEL=DEBUG
DATABASE_PATH=./data/shadowbox.db
TEMP_PATH=./temp
MAX_FILE_SIZE=104857600
ENVEOF
fi
