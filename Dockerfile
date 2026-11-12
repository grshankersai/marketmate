# Use an official slim Python base image
FROM python:3.11-slim

# Prevent Python from writing .pyc files and buffer output
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /app

# Install system dependencies (supervisor)
RUN apt-get update && apt-get install -y --no-install-recommends \
    supervisor \
    && rm -rf /var/lib/apt/lists/*

# Install Python requirements
COPY requirement.txt .
RUN pip install --no-cache-dir -r requirement.txt

# Copy application files and supervisor configuration
COPY api.py agent.py front_end.py supervisord.conf ./

# Expose the Streamlit web port
EXPOSE 7860

# Start supervisor as the primary container process
CMD ["/usr/bin/supervisord", "-c", "/app/supervisord.conf"]