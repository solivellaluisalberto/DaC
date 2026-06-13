#!/usr/bin/env python3
"""
Script para sincronizar archivos o carpetas Markdown con Confluence.

Soporta Confluence Cloud y Data Center/Server mediante variables de entorno.

Si se pasa una carpeta, se crea toda la estructura jerárquica en Confluence:
- Cada carpeta se convierte en una página de Confluence (página padre).
- Cada archivo .md se sincroniza como página hija de su carpeta contenedora.

Si se pasa un archivo, se sincroniza directamente como hasta ahora.

El título de la página se extrae automáticamente del primer encabezado nivel 1 (#)
del Markdown o del campo `page_title` en el frontmatter YAML.

Variables de entorno requeridas:
    CONFLUENCE_URL        - URL base de Confluence (ej: https://miempresa.atlassian.net/wiki)
    CONFLUENCE_USER       - Email del usuario (Cloud) o nombre de usuario (Server)
    CONFLUENCE_API_TOKEN  - API Token (Cloud) o password (Server)
    CONFLUENCE_SPACE_KEY  - Clave del espacio (ej: PROY)

Opcional:
    CONFLUENCE_PARENT_ID  - ID de la página padre raíz (para carpetas y archivos sin padre definido)
"""

import argparse
import os
import sys
import re
import time
import html
import markdown
import requests
import yaml
from urllib.parse import urljoin


class ConfluenceSync:
    def __init__(self, dry_run=False):
        self.url = os.environ.get("CONFLUENCE_URL", "").rstrip("/") + "/"
        self.user = os.environ.get("CONFLUENCE_USER", "")
        self.token = os.environ.get("CONFLUENCE_API_TOKEN", "")
        self.space_key = os.environ.get("CONFLUENCE_SPACE_KEY", "")
        self.parent_id = os.environ.get("CONFLUENCE_PARENT_ID", "")
        self.dry_run = dry_run
        self._folder_cache = {}  # ruta_relativa -> confluence_id

        self._validate_config()
        self.session = requests.Session()
        self.session.headers.update({
            "Content-Type": "application/json",
            "Accept": "application/json"
        })
        # Basic Auth nativo de requests
        self.session.auth = (self.user, self.token)

        # Verificar conectividad antes de continuar
        self._verify_connection()

    def _validate_config(self):
        missing = []
        for key in ["CONFLUENCE_URL", "CONFLUENCE_USER", "CONFLUENCE_API_TOKEN", "CONFLUENCE_SPACE_KEY"]:
            if not os.environ.get(key):
                missing.append(key)
        if missing:
            print(f"[ERROR] Faltan variables de entorno: {', '.join(missing)}")
            sys.exit(1)

    def _parse_frontmatter(self, md_file):
        """Lee y parsea el frontmatter YAML del archivo Markdown.
        
        Devuelve (metadata_dict, resto_del_contenido).
        Si no hay frontmatter, devuelve ({}, contenido_completo).
        """
        with open(md_file, "r", encoding="utf-8") as f:
            content = f.read()
        
        if content.startswith("---"):
            parts = content.split("---", 2)
            if len(parts) >= 3:
                try:
                    metadata = yaml.safe_load(parts[1])
                    return metadata if metadata else {}, parts[2].strip()
                except yaml.YAMLError as e:
                    print(f"[WARNING] Error parseando frontmatter YAML: {e}")
                    return {}, content
        return {}, content

    def _extract_title(self, md_file):
        """Extrae el título del frontmatter o del primer encabezado nivel 1 (#)."""
        metadata, _ = self._parse_frontmatter(md_file)
        
        # Prioridad 1: page_title en frontmatter
        if metadata.get("page_title"):
            return metadata["page_title"].strip()
        
        # Prioridad 2: primer encabezado nivel 1
        with open(md_file, "r", encoding="utf-8") as f:
            for line in f:
                stripped = line.strip()
                if stripped.startswith("# "):
                    return stripped[2:].strip()
        
        print("[WARNING] No se encontró un título con '# ' en el archivo. Usando fallback.")
        return "Documentación sin título"

    def _verify_connection(self):
        """Verifica que la URL y el espacio de Confluence sean válidos."""
        print(f"[DEBUG] URL configurada: {self.url}")
        print(f"[DEBUG] Usuario: {self.user}")
        print(f"[DEBUG] Space Key: {self.space_key}")
        
        # Verificar que la URL parece correcta
        if not self.url.rstrip("/").endswith("/wiki"):
            print(f"[WARNING] La URL '{self.url}' no termina en '/wiki'. Para Confluence Cloud, la URL suele ser 'https://<dominio>.atlassian.net/wiki'")
        
        # Probar conectividad básica
        test_url = urljoin(self.url, "rest/api/space")
        print(f"[DEBUG] Probando conexión a: {test_url}")
        try:
            resp = self.session.get(test_url, timeout=10)
            print(f"[DEBUG] Status code: {resp.status_code}")
            print(f"[DEBUG] Respuesta: {resp.text[:500]}")
            if resp.status_code == 404:
                print(f"[ERROR] No se puede conectar a Confluence en '{self.url}'. Verifica que la URL sea correcta.")
                print(f"[ERROR] Para Confluence Cloud, la URL debe ser algo como: https://<tu-dominio>.atlassian.net/wiki")
                sys.exit(1)
            resp.raise_for_status()
        except requests.exceptions.RequestException as e:
            print(f"[ERROR] No se puede conectar a Confluence: {e}")
            print(f"[ERROR] Verifica que la URL '{self.url}' sea correcta y que tengas acceso.")
            sys.exit(1)
        
        # Verificar que el espacio existe
        space_url = urljoin(self.url, f"rest/api/space/{self.space_key}")
        print(f"[DEBUG] Verificando espacio: {space_url}")
        resp = self.session.get(space_url)
        print(f"[DEBUG] Status code del espacio: {resp.status_code}")
        print(f"[DEBUG] Respuesta del espacio: {resp.text[:500]}")
        if resp.status_code == 404:
            print(f"[ERROR] El espacio '{self.space_key}' no existe o no tienes permisos para verlo.")
            print(f"[ERROR] Verifica que el espacio esté correctamente escrito en la variable CONFLUENCE_SPACE_KEY.")
            sys.exit(1)
        resp.raise_for_status()
        print(f"[INFO] Conexión a Confluence OK. Espacio '{self.space_key}' verificado.")

    def _convert_code_blocks(self, html_content):
        """Convierte bloques <pre><code> a la macro 'code' de Confluence."""
        def replace_code(match):
            lang = match.group(1) or ""
            code_text = match.group(2)
            # Desescapar entidades HTML para que se vean bien en Confluence
            code_text = html.unescape(code_text)
            # Escapar el delimitador CDATA si aparece en el código
            code_text = code_text.replace("]]>", "]]]]><![CDATA[>")
            return (
                f'<ac:structured-macro ac:name="code">'
                f'<ac:parameter ac:name="language">{lang}</ac:parameter>'
                f'<ac:plain-text-body><![CDATA[{code_text}]]></ac:plain-text-body>'
                f'</ac:structured-macro>'
            )
        
        # Reemplaza todos los bloques <pre><code class="language-xxx">...</code></pre>
        pattern = r'<pre><code(?: class="language-([^"]*)")?>(.*?)</code></pre>'
        return re.sub(pattern, replace_code, html_content, flags=re.DOTALL)

    def _md_to_html(self, md_file):
        with open(md_file, "r", encoding="utf-8") as f:
            text = f.read()
        # Convertir markdown a HTML
        html_content = markdown.markdown(text, extensions=["tables", "fenced_code", "toc"])
        # Convertir bloques de código a macro Confluence
        html_content = self._convert_code_blocks(html_content)
        # Confluence requiere que el body esté envuelto en un macro storage si es XHTML
        return f"<div>{html_content}</div>"

    def _request_with_retry(self, method, url, **kwargs):
        """Ejecuta una petición HTTP con reintentos automáticos ante 429 (rate limit)."""
        max_retries = 3
        for attempt in range(1, max_retries + 1):
            if self.dry_run:
                return None
            resp = self.session.request(method, url, **kwargs)
            if resp.status_code == 429:
                wait = 2 ** attempt  # backoff exponencial: 2, 4, 8 seg
                print(f"[WARNING] Rate limit (429). Esperando {wait}s... (intento {attempt}/{max_retries})")
                time.sleep(wait)
                continue
            resp.raise_for_status()
            return resp
        raise requests.exceptions.HTTPError("Rate limit persistente después de 3 reintentos.")

    def _find_page(self, title=None, ancestor_id=None):
        """Busca una página por título en el espacio. Opcionalmente filtra por ancestro."""
        search_url = urljoin(self.url, "rest/api/content")
        params = {
            "type": "page",
            "spaceKey": self.space_key,
            "title": title,
            "expand": "version,body.storage"
        }
        resp = self._request_with_retry("GET", search_url, params=params)
        data = resp.json()
        results = data.get("results", [])
        if not results:
            return None
        if ancestor_id and len(results) > 1:
            # Desambiguar: preferir página que cuelga del ancestor_id
            for r in results:
                ancestors = r.get("ancestors", [])
                if any(str(a.get("id")) == str(ancestor_id) for a in ancestors):
                    return r
        return results[0]

    def _create_page(self, html_content, title=None, parent_id=None):
        """Crea una nueva página en Confluence."""
        if self.dry_run:
            print(f"[DRY-RUN] Crearía página: '{title}'")
            return {"id": "dry-run", "_links": {"base": "", "webui": ""}}
        create_url = urljoin(self.url, "rest/api/content")
        payload = {
            "type": "page",
            "title": title,
            "space": {"key": self.space_key},
            "body": {
                "storage": {
                    "value": html_content,
                    "representation": "storage"
                }
            }
        }
        if parent_id:
            payload["ancestors"] = [{"id": int(parent_id)}]

        resp = self._request_with_retry("POST", create_url, json=payload)
        return resp.json()

    def _update_page(self, page, html_content, title=None, parent_id=None):
        """Actualiza una página existente en Confluence."""
        if self.dry_run:
            print(f"[DRY-RUN] Actualizaría página: '{title}' (ID: {page['id']})")
            return {"id": page["id"], "_links": {"base": "", "webui": ""}}
        page_id = page["id"]
        version = page["version"]["number"]
        update_url = urljoin(self.url, f"rest/api/content/{page_id}")
        payload = {
            "type": "page",
            "title": title,
            "version": {"number": version + 1},
            "body": {
                "storage": {
                    "value": html_content,
                    "representation": "storage"
                }
            }
        }
        if parent_id:
            payload["ancestors"] = [{"id": int(parent_id)}]

        resp = self._request_with_retry("PUT", update_url, json=payload)
        return resp.json()

    def _find_or_create_folder_page(self, title, parent_id=None):
        """Busca una página por título. Si existe, devuelve el ID. Si no, la crea como carpeta."""
        # Revisar cache primero
        cache_key = f"{parent_id or 'root'}::{title}"
        if cache_key in self._folder_cache:
            cached_id = self._folder_cache[cache_key]
            print(f"[INFO] Carpeta encontrada en cache: '{title}' (ID: {cached_id})")
            return cached_id

        page = self._find_page(title=title, ancestor_id=parent_id)
        if page:
            print(f"[INFO] Carpeta existente encontrada: '{title}' (ID: {page['id']})")
            self._folder_cache[cache_key] = page["id"]
            return page["id"]

        # Crear nueva página (carpeta)
        print(f"[INFO] Creando carpeta: '{title}'...")
        body = f'<div><p>Carpeta auto-generada: <strong>{title}</strong>.</p></div>'
        result = self._create_page(html_content=body, title=title, parent_id=parent_id)
        print(f"[SUCCESS] Carpeta creada: '{title}' (ID: {result['id']})")
        self._folder_cache[cache_key] = result["id"]
        # Pequeña pausa para evitar rate limiting en creaciones masivas
        time.sleep(0.3)
        return result["id"]

    def _sync_directory(self, dir_path, parent_id=None):
        """Procesa un directorio recursivamente, creando la estructura de carpetas en Confluence."""
        abs_path = os.path.abspath(dir_path)
        rel_path = os.path.relpath(abs_path, os.getcwd())

        # Determinar parent_id para esta carpeta
        folder_parent = parent_id if parent_id is not None else self.parent_id
        if folder_parent:
            folder_parent = int(folder_parent)

        # Crear/obtener la página de esta carpeta
        folder_title = os.path.basename(dir_path)
        try:
            folder_id = self._find_or_create_folder_page(folder_title, parent_id=folder_parent)
        except requests.exceptions.HTTPError as e:
            print(f"[ERROR] Fallo al crear/obtener carpeta '{folder_title}': {e}")
            raise

        # Recorrer contenido (ignorar ocultos y symlinks)
        items = sorted(os.listdir(dir_path))
        subdirs = [i for i in items
                   if not i.startswith('.')
                   and not os.path.islink(os.path.join(dir_path, i))
                   and os.path.isdir(os.path.join(dir_path, i))]
        files = [i for i in items
                 if not i.startswith('.')
                 and not os.path.islink(os.path.join(dir_path, i))
                 and i.lower().endswith('.md')
                 and os.path.isfile(os.path.join(dir_path, i))]

        total_items = len(subdirs) + len(files)
        current = 0

        # Procesar subcarpetas primero (para que sus hijos tengan IDs)
        for subdir in subdirs:
            current += 1
            subdir_path = os.path.join(dir_path, subdir)
            print(f"\n[{current}/{total_items}] Procesando subcarpeta: {subdir}")
            self._sync_directory(subdir_path, parent_id=folder_id)

        # Procesar archivos .md
        for f in files:
            current += 1
            file_path = os.path.join(dir_path, f)
            print(f"\n[{current}/{total_items}] Procesando archivo: {f}")
            self._sync_file(file_path, parent_id=folder_id)

    def _sync_file(self, file_path, parent_id=None):
        """Sincroniza un archivo individual, con parent_id opcional."""
        page_title = self._extract_title(file_path)

        print(f"\n{'='*60}")
        print(f"[INFO] Sincronizando archivo: {file_path}")
        print(f"[INFO] Título: {page_title}")
        print(f"{'='*60}")

        # Leer metadatos del frontmatter
        metadata, _ = self._parse_frontmatter(file_path)

        # Resolver confluence_id si existe en frontmatter
        confluence_id = metadata.get("confluence_id")

        html_content = self._md_to_html(file_path)
        print(f"[INFO] Convirtiendo a HTML ({len(html_content)} chars)...")

        if confluence_id:
            print(f"[INFO] Usando confluence_id '{confluence_id}' desde frontmatter. Actualizando página específica...")
            try:
                page_url = urljoin(self.url, f"rest/api/content/{confluence_id}")
                resp = self._request_with_retry("GET", page_url, params={"expand": "version,body.storage"})
                page = resp.json()
                result = self._update_page(page, html_content, title=page_title, parent_id=parent_id)
                print(f"[SUCCESS] Página actualizada (ID: {confluence_id}): {result['_links']['base']}{result['_links']['webui']}")
            except requests.exceptions.HTTPError as e:
                if e.response.status_code == 404:
                    print(f"[ERROR] No se encontró la página con ID '{confluence_id}'. Verifica que el ID sea correcto.")
                else:
                    raise
        else:
            print(f"[INFO] Buscando página '{page_title}' en espacio '{self.space_key}'...")
            page = self._find_page(title=page_title, ancestor_id=parent_id)

            if page:
                print(f"[INFO] Página encontrada (ID: {page['id']}). Actualizando...")
                result = self._update_page(page, html_content, title=page_title, parent_id=parent_id)
                print(f"[SUCCESS] Página actualizada: {result['_links']['base']}{result['_links']['webui']}")
            else:
                print(f"[INFO] Página no encontrada. Creando nueva...")
                result = self._create_page(html_content, title=page_title, parent_id=parent_id)
                print(f"[SUCCESS] Página creada: {result['_links']['base']}{result['_links']['webui']}")
        # Pequeña pausa para evitar rate limiting
        time.sleep(0.3)

    def run(self, path):
        """Método principal: decide si sincronizar archivo o directorio."""
        if not path:
            print("[ERROR] No se especificó archivo ni directorio.")
            sys.exit(1)
        
        if os.path.isdir(path):
            self._sync_directory(path)
        elif os.path.isfile(path):
            if not path.lower().endswith('.md'):
                print(f"[WARNING] El archivo '{path}' no es un .md. Se omitirá.")
                return
            self._sync_file(path)
        else:
            print(f"[ERROR] No se encuentra el path: {path}")
            sys.exit(1)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Sync Markdown files or directories to Confluence")
    parser.add_argument("paths", nargs="+", help="Archivos o carpetas Markdown a sincronizar")
    parser.add_argument("--dry-run", action="store_true", help="Simula la ejecución sin crear ni actualizar páginas en Confluence")
    args = parser.parse_args()

    errors = []
    # Crear una sola instancia para reutilizar la conexión
    sync = ConfluenceSync(dry_run=args.dry_run)
    
    for path in args.paths:
        print(f"\n{'='*60}")
        print(f"[INFO] Procesando: {path}")
        if args.dry_run:
            print(f"[DRY-RUN] Modo simulación activado. No se realizarán cambios.")
        print(f"{'='*60}")
        try:
            if not os.path.exists(path):
                print(f"[ERROR] No se encuentra el path: {path}")
                errors.append(path)
                continue
            sync.run(path)
        except requests.exceptions.HTTPError as e:
            print(f"[ERROR] Error HTTP en '{path}': {e}")
            if e.response is not None:
                print(f"[ERROR] Respuesta: {e.response.text}")
            errors.append(path)
        except Exception as e:
            print(f"[ERROR] Error en '{path}': {e}")
            errors.append(path)

    if errors:
        print(f"\n[ERROR] Fallaron {len(errors)} path(s): {', '.join(errors)}")
        sys.exit(1)
    else:
        print(f"\n[SUCCESS] Todos los paths procesados correctamente.")
