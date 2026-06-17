# confluence-sync

Docker image that syncs Markdown files with **Confluence** as wiki pages.

- Supports **individual files** and **full directory hierarchies**.
- Compatible with **Confluence Cloud** and **Confluence Server/Data Center**.
- Multi-platform: **Bitbucket Pipelines**, **GitHub Actions**, **GitLab CI**.

---

## What it does

When you run this Docker image, it reads the `.md` files from your repository, converts them to HTML, and syncs them with Confluence:

- **Individual files** → creates or updates them as Confluence pages.
- **Directories** → builds the full folder hierarchy in Confluence (each folder becomes a parent page, each `.md` file becomes a child page).
- **YAML frontmatter** → supports `page_title` (custom title) and `confluence_id` (update a specific existing page by ID).
- **Rate limiting** → automatic retries with exponential backoff on HTTP 429.

---

## Environment Variables

### Required

| Variable | Description | Example |
|----------|-------------|---------|
| `CONFLUENCE_URL` | Confluence base URL | `https://mycompany.atlassian.net/wiki` |
| `CONFLUENCE_USER` | Email (Cloud) or username (Server) | `user@company.com` |
| `CONFLUENCE_API_TOKEN` | API Token (Cloud) or password (Server) | `ATBB...` |
| `CONFLUENCE_SPACE_KEY` | Confluence space key | `PROJ`, `DOCS`, `TEAM` |
| `FILES` | Files or directories to sync (space-separated) | `README.md docs/ manual.md` |

### Optional

| Variable | Description | Default |
|----------|-------------|---------|
| `CONFLUENCE_PARENT_ID` | Root parent page ID in Confluence | — |
| `DRY_RUN` | `true` to simulate without publishing changes | `false` |

---

## Docker Image Tags

| Tag | Branch | Description |
|-----|--------|-------------|
| `latest` | `main` | Stable release |
| `develop` | `develop` | Latest development build |
| `<run_number>` | `main` | Specific build from the `main` branch |

## Platform Usage

### Bitbucket Pipelines

```yaml
pipelines:
  branches:
    main:
      - step:
          name: Sync docs to Confluence
          script:
            - pipe: docker://solivellaluis/confluence-sync:latest
              variables:
                CONFLUENCE_URL: $CONFLUENCE_URL
                CONFLUENCE_USER: $CONFLUENCE_USER
                CONFLUENCE_API_TOKEN: $CONFLUENCE_API_TOKEN
                CONFLUENCE_SPACE_KEY: "PROJ"
                CONFLUENCE_PARENT_ID: "123456"
                FILES: "README.md docs/ manual.md"
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
          CONFLUENCE_SPACE_KEY: "PROJ"
          CONFLUENCE_PARENT_ID: "123456"
          FILES: "README.md docs/ manual.md"
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
    CONFLUENCE_SPACE_KEY: "PROJ"
    CONFLUENCE_PARENT_ID: "123456"
    FILES: "README.md docs/ manual.md"
    DRY_RUN: "false"
  script:
    - /pipe.sh
  rules:
    - if: $CI_COMMIT_BRANCH == "main"
```

---

## Markdown Frontmatter

You can control how each file is synced by adding a YAML frontmatter block at the top of the `.md` file:

```markdown
---
page_title: "Custom title in Confluence"
confluence_id: "589829"
parent_id: "123456"
---

# Your Markdown content...
```

| Field | Purpose |
|-------|---------|
| `page_title` | Page title in Confluence (if not set, uses the first `# H1`) |
| `confluence_id` | If present, updates the page with that exact ID (skips search by title) |
| `parent_id` | If present, overrides the inherited parent page ID for this specific file |

---

## Local Build

```bash
# Build the image locally
docker build -t solivellaluis/confluence-sync:local .

# Run locally with DRY_RUN to test
docker run -it --rm \
  -v $(pwd):/workspace \
  -e CONFLUENCE_URL="https://yourcompany.atlassian.net/wiki" \
  -e CONFLUENCE_USER="your@email.com" \
  -e CONFLUENCE_API_TOKEN="ATBB..." \
  -e CONFLUENCE_SPACE_KEY="PROJ" \
  -e FILES="README.md" \
  -e DRY_RUN="true" \
  solivellaluis/confluence-sync:local
```

---

## Contributing

Contributions are welcome. If you want to improve the script, add new features, or fix a bug, feel free to open a pull request.

---

## Repository Structure

```
.
├── .github/
│   └── workflows/
│       └── docker-publish.yml      # GitHub Actions CI/CD
├── scripts/
│   └── sync_to_confluence.py      # Main Python script
├── .dockerignore
├── Dockerfile                     # Docker image definition
├── pipe.sh                        # Container entrypoint
├── pipe.yml                       # Pipe metadata (Bitbucket)
├── requirements.txt               # Python dependencies
└── README.md                      # This file
```

| File | Description |
|------|-------------|
| `Dockerfile` | `python:3.11-slim` image with dependencies and the sync script |
| `pipe.sh` | Entrypoint that detects the workspace (Bitbucket/GitLab/GitHub) and runs the script |
| `sync_to_confluence.py` | Main sync script: converts Markdown to HTML, creates/updates Confluence pages |
| `pipe.yml` | Pipe metadata for Bitbucket Pipelines (variable documentation) |
| `docker-publish.yml` | GitHub Actions workflow that builds and publishes the image to Docker Hub on `main` (`latest`) and `develop` (`develop`) |

---

## License

MIT
