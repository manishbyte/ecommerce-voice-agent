
FROM python:3.12-slim

WORKDIR /srv

ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1

# Install backend dependencies
COPY backend/requirements.txt backend/requirements.txt

RUN pip install --no-cache-dir -r backend/requirements.txt

# Copy backend source and shared data
COPY backend backend
COPY data data

WORKDIR /srv/backend

EXPOSE 8000

# Start FastAPI using the custom main.py entry point
CMD ["python", "-m", "app.main"]
