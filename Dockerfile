# Wir nutzen eine schlanke Python-Version
FROM python:3.11-slim

# System-Abhängigkeiten für Bildverarbeitung und PDF
RUN apt-get update && apt-get install -y \
    build-essential \
    curl \
    software-properties-common \
    git \
    && rm -rf /var/lib/apt/lists/*

# Arbeitsverzeichnis im Container festlegen
WORKDIR /app

# Den Code und die Anforderungen kopieren
COPY . .

# Python-Bibliotheken installieren
RUN pip install --no-cache-dir -r requirements.txt

# Den Port für Fly.io öffnen
EXPOSE 8080

# Der Befehl, der die App startet
CMD ["streamlit", "run", "app.py", "--server.port=8080", "--server.address=0.0.0.0"]
