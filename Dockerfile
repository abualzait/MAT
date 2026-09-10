FROM python:3.11-slim

WORKDIR /app

# Ensure persistent data directory exists
RUN mkdir -p /data

# Declare volume for data persistence across container restarts
VOLUME ["/data"]

# Copy all project files
COPY . .

# Expose port
EXPOSE 8080

# Start the MAT server
CMD ["python", "server.py"]
