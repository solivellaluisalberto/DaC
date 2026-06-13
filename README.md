# confluence-sync

Docker image que sincroniza archivos Markdown con **Confluence** como páginas wiki.

- **Soporta** archivos individuales y directorios completos (estructura jerárquica).
- **Compatible** con Confluence Cloud y Confluence Server/Data Center.
- **Multiplataforma**: Bitbucket Pipelines, GitHub Actions, GitLab CI.

---

## Qué hace

Cuando ejecutas esta imagen Docker, lee los archivos `.md` de tu repo, los convierte a HTML y los sincroniza con Confluence:

- **Archivos individuales** → se crean/actualizan como páginas.
- **Directorios** → se crea la jerarquía de carpetas en Confluence (cada carpeta es una página padre, cada archivo `.md` es una página hija).
- **Frontmatter YAML** → soporta `page_title` (título personalizado) y `confluence_id` (ID de página existente para actualizar).
- **Rate limiting** → reintentos automáticos con backoff exponencial ante HTTP 429.

---

## Variables de entorno

### Requeridas

| Variable | Descripción | Ejemplo |
|----------|-------------|---------|
| `CONFLUENCE_URL` | URL base de Confluence | `https://miempresa.atlassian.net/wiki` |
| `CONFLUENCE_USER` | Email (Cloud) o usuario (Server) | `usuario@empresa.com` |
| `CONFLUENCE_API_TOKEN` | API Token (Cloud) o password (Server) | `ATBB...` |
| `CONFLUENCE_SPACE_KEY` | Clave del espacio | `PROY`, `DOCS`, `TEAM` |
| `FILES` | Archivos/directorios a sincronizar (separados por espacio) | `README.md docs/ manual.md` |

### Opcionales

| Variable | Descripción | Default |
|----------|-------------|---------|
| `CONFLUENCE_PARENT_ID` | ID de la página padre raíz en Confluence | — |
| `DRY_RUN` | `true` para simular sin publicar cambios | `false` |

---

## Uso por plataforma

### Bitbucket Pipelines

```yaml
pipelines:
  branches:
    main:
      - step:
          name: Sync docs a Confluence
          script:
            - pipe: docker://solivellaluis/confluence-sync:latest
              variables:
                CONFLUENCE_URL: $CONFLUENCE_URL
                CONFLUENCE_USER: $CONFLUENCE_USER
                CONFLUENCE_API_TOKEN: $CONFLUENCE_API_TOKEN
                CONFLUENCE_SPACE_KEY: "PROY"
                CONFLUENCE_PARENT_ID: "123456"
                FILES: "README.md docs/ manual-usuario.md"
                DRY_RUN: "false"
```

### GitHub Actions

```yaml
name: Sync docs to Confluence

on:
  push:
    branches: [main]

jobs:
  sync:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - name: Sync to Confluence
        uses: docker://solivellaluis/confluence-sync:latest
        env:
          CONFLUENCE_URL: ${{ secrets.CONFLUENCE_URL }}
          CONFLUENCE_USER: ${{ secrets.CONFLUENCE_USER }}
          CONFLUENCE_API_TOKEN: ${{ secrets.CONFLUENCE_API_TOKEN }}
          CONFLUENCE_SPACE_KEY: "PROY"
          CONFLUENCE_PARENT_ID: "123456"
          FILES: "README.md docs/ manual-usuario.md"
          DRY_RUN: "false"
```

### GitLab CI

```yaml
sync-confluence:
  image:
    name: solivellaluis/confluence-sync:latest
    entrypoint: [""]
  variables:
    CONFLUENCE_URL: $CONFLUENCE_URL
    CONFLUENCE_USER: $CONFLUENCE_USER
    CONFLUENCE_API_TOKEN: $CONFLUENCE_API_TOKEN
    CONFLUENCE_SPACE_KEY: "PROY"
    CONFLUENCE_PARENT_ID: "123456"
    FILES: "README.md docs/ manual-usuario.md"
    DRY_RUN: "false"
  script:
    - /pipe.sh
  rules:
    - if: $CI_COMMIT_BRANCH == "main"
```

---

## Frontmatter en los archivos Markdown

Puedes controlar la sincronización de cada archivo añadiendo un bloque YAML al inicio del `.md`:

```markdown
---
page_title: "Título personalizado en Confluence"
confluence_id: "589829"
---

# Tu contenido Markdown...
```

| Campo | Uso |
|-------|-----|
| `page_title` | Título de la página en Confluence (si no se indica, usa el primer `# H1`) |
| `confluence_id` | Si existe, actualiza la página con ese ID directamente (sin buscar por título) |

---

## Build local

```bash
# Clonar el repo y construir la imagen
docker build -t solivellaluis/confluence-sync:local .

# Ejecutar localmente (simulado con DRY_RUN)
docker run -it --rm \
  -v $(pwd):/workspace \
  -e CONFLUENCE_URL="https://tuempresa.atlassian.net/wiki" \
  -e CONFLUENCE_USER="tu@email.com" \
  -e CONFLUENCE_API_TOKEN="ATBB..." \
  -e CONFLUENCE_SPACE_KEY="PROY" \
  -e FILES="README.md" \
  -e DRY_RUN="true" \
  solivellaluis/confluence-sync:local
```

---

## Publicar una nueva versión

Este repo utiliza **GitHub Actions** para automatizar el build y push de la imagen Docker:

1. Configura dos secrets en el repositorio de GitHub:
   - **Settings → Secrets and variables → Actions → New repository secret**
   - `DOCKERHUB_USERNAME` → `solivellaluis`
   - `DOCKERHUB_TOKEN` → tu Access Token de Docker Hub

2. Cualquier **push a `main`** compila y publica automáticamente:
   - `solivellaluis/confluence-sync:latest`
   - `solivellaluis/confluence-sync:${GITHUB_RUN_NUMBER}` (número incremental para rollback)

3. En **PRs o ramas que no sean `main`**, la imagen se compila pero **no se publica** (validación).

---

## Estructura del repositorio

```
.
├── .github/
│   └── workflows/
│       └── docker-publish.yml      # GitHub Actions: build + push a Docker Hub
├── scripts/
│   └── sync_to_confluence.py      # Script principal (Python)
├── .dockerignore
├── Dockerfile                     # Definición de la imagen
├── pipe.sh                        # Entrypoint del contenedor
├── pipe.yml                       # Metadata del pipe (para Bitbucket)
├── requirements.txt               # Dependencias Python
└── README.md                      # Este archivo
```

| Archivo | Descripción |
|---------|-------------|
| `Dockerfile` | Imagen basada en `python:3.11-slim` con las dependencias y el script |
| `pipe.sh` | Entrypoint que detecta el workspace (Bitbucket/GitLab/GitHub) y ejecuta el script |
| `sync_to_confluence.py` | Script de sincronización: convierte Markdown a HTML, crea/actualiza páginas en Confluence |
| `pipe.yml` | Metadata del pipe para Bitbucket Pipelines (documentación de variables) |
| `docker-publish.yml` | Workflow de GitHub Actions que compila y publica la imagen en Docker Hub |

---

## Licencia

MIT
