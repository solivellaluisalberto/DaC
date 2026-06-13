#!/bin/bash
set -e

# ---------------------------------------------------------------------------
# Entrypoint del Bitbucket Pipe: solivellaluis/confluence-sync
#
# Variables de entorno requeridas:
#   CONFLUENCE_URL        - URL base de Confluence
#   CONFLUENCE_USER       - Email (Cloud) o usuario (Server)
#   CONFLUENCE_API_TOKEN  - API Token (Cloud) o password (Server)
#   CONFLUENCE_SPACE_KEY  - Clave del espacio (ej: PROY)
#
# Variables opcionales:
#   CONFLUENCE_PARENT_ID  - ID de la página padre raíz
#   FILES                 - Archivos/directorios a sincronizar (separados por espacio)
#   DRY_RUN               - "true" para simular sin publicar cambios
# ---------------------------------------------------------------------------

# Detectar el directorio del workspace en distintas plataformas CI:
#   - Bitbucket Pipelines: $BITBUCKET_CLONE_DIR
#   - GitLab CI:           $CI_PROJECT_DIR
#   - GitHub Actions:      $GITHUB_WORKSPACE
# Fallback: directorio actual (ejecución local)
WORKDIR="${BITBUCKET_CLONE_DIR:-${CI_PROJECT_DIR:-${GITHUB_WORKSPACE:-$(pwd)}}}"

echo "[INFO] Workspace: $WORKDIR"
cd "$WORKDIR"

# Validar que se hayan indicado archivos/directorios a sincronizar
if [ -z "$FILES" ]; then
  echo "[ERROR] La variable FILES es obligatoria."
  echo "[ERROR] Especifica los archivos o directorios a sincronizar separados por espacios."
  echo "[ERROR] Ejemplo: FILES=\"README.md docs/ manual-usuario.md\""
  exit 1
fi

# Construir el flag --dry-run si corresponde
DRY_RUN_FLAG=""
if [ "${DRY_RUN}" = "true" ]; then
  DRY_RUN_FLAG="--dry-run"
  echo "[INFO] Modo DRY RUN activado. No se realizarán cambios en Confluence."
fi

echo "[INFO] Archivos/directorios a sincronizar: $FILES"
echo "[INFO] Iniciando sincronización con Confluence..."
echo "------------------------------------------------------------"

# Ejecutar el script de sincronización
# $FILES se expande intencionalmente sin comillas para separar por palabras
# shellcheck disable=SC2086
python /scripts/sync_to_confluence.py $FILES $DRY_RUN_FLAG
