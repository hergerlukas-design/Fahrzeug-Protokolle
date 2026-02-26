# Wir nutzen eine schlanke Python-Version
FROM python:3.11-slim

# System-Abhängigkeiten (bereinigt für Fly.io)
RUN apt-get update && apt-get install -y \
    build-essential \
    curl \
    git \
    && rm -rf /var/lib/apt/lists/*

# Arbeitsverzeichnis
WORKDIR /app

# Code kopieren
COPY . .

# Python-Pakete installieren
RUN pip install --no-cache-dir -r requirements.txt

# Port für Fly.io
EXPOSE 8080

# Startbefehl
CMD ["streamlit", "run", "app.py", "--server.port=8080", "--server.address=0.0.0.0"]
