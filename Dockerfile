FROM python:3.11-slim

WORKDIR /app

# Ensure persistent data directory exists
RUN mkdir -p /data && chmod 777 /data

# Declare volume for data persistence across container restarts
VOLUME ["/data"]

# Copy all project files
COPY . .

# Expose default port
EXPOSE 7860
EXPOSE 8080

# Default port for Hugging Face Spaces
ENV PORT=7860

# Start the MAT server
CMD ["python", "server.py"]

