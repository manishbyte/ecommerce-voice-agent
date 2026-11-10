
FROM python:3.12-slim

WORKDIR /app

ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1

# Install frontend dependencies
COPY frontend/requirements.txt requirements.txt

RUN pip install --no-cache-dir -r requirements.txt

# Copy frontend source
COPY frontend/ .

EXPOSE 8501

CMD ["streamlit", "run", "app.py", "--server.address", "0.0.0.0", "--server.port", "8501"]
