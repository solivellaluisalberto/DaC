FROM python:3.11-slim

LABEL maintainer="solivellaluis"
LABEL org.opencontainers.image.title="confluence-sync"
LABEL org.opencontainers.image.description="Sincroniza archivos Markdown con Confluence. Úsalo como pipe en Bitbucket Pipelines."
LABEL org.opencontainers.image.source="https://hub.docker.com/r/solivellaluis/confluence-sync"

WORKDIR /

# Instalar dependencias Python
COPY requirements.txt /requirements.txt
RUN pip install --no-cache-dir -r /requirements.txt

# Copiar el script de sincronización
COPY scripts/sync_to_confluence.py /scripts/sync_to_confluence.py

# Copiar y preparar el entrypoint
COPY pipe.sh /pipe.sh
RUN chmod +x /pipe.sh

ENTRYPOINT ["/pipe.sh"]
