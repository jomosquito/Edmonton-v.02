#!/bin/bash
set -e

# Run migrations
echo "Running database migrations..."
python migrations.py

# Start the application
echo "Starting the application..."
python main.py