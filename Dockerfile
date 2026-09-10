FROM python:3.11-slim

WORKDIR /app

# Copy all project files
COPY . .

# Expose the port Fly.io will route to
EXPOSE 8080

# Start the MAT server
CMD ["python", "server.py"]
