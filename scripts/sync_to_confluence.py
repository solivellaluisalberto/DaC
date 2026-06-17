#!/usr/bin/env python3
"""
Script to sync Markdown files or folders with Confluence.

Supports Confluence Cloud and Data Center/Server via environment variables.

If a folder is passed, the entire hierarchical structure is created in Confluence:
- Each folder becomes a Confluence page (parent page).
- Each .md file is synced as a child page of its containing folder.

If a file is passed, it is synced directly as before.

The page title is automatically extracted from the first level 1 heading (#)
in the Markdown or from the `page_title` field in the YAML frontmatter.

Required environment variables:
    CONFLUENCE_URL        - Confluence base URL (e.g., https://mycompany.atlassian.net/wiki)
    CONFLUENCE_USER       - User email (Cloud) or username (Server)
    CONFLUENCE_API_TOKEN  - API Token (Cloud) or password (Server)
    CONFLUENCE_SPACE_KEY  - Space key (e.g., PROJ)

Optional:
    CONFLUENCE_PARENT_ID  - Root parent page ID (for folders and files without a defined parent)
"""

import argparse
import base64
import hashlib
import json
import os
import sys
import re
import time
import html
import markdown
import requests
import yaml
import zlib
from urllib.parse import urljoin


class ConfluenceSync:
    def __init__(self, dry_run=False):
        self.url = os.environ.get("CONFLUENCE_URL", "").rstrip("/") + "/"
        self.user = os.environ.get("CONFLUENCE_USER", "")
        self.token = os.environ.get("CONFLUENCE_API_TOKEN", "")
        self.space_key = os.environ.get("CONFLUENCE_SPACE_KEY", "")
        self.parent_id = os.environ.get("CONFLUENCE_PARENT_ID", "")
        self.dry_run = dry_run
        self.mermaid_show_source = os.environ.get("MERMAID_SHOW_SOURCE", "true").lower() in ("1", "true", "yes")
        self._folder_cache = {}  # relative_path -> confluence_id

        self._validate_config()
        self.session = requests.Session()
        self.session.headers.update({
            "Content-Type": "application/json",
            "Accept": "application/json"
        })
        # requests native Basic Auth
        self.session.auth = (self.user, self.token)

        # Verify connectivity before proceeding
        self._verify_connection()

    def _validate_config(self):
        missing = []
        for key in ["CONFLUENCE_URL", "CONFLUENCE_USER", "CONFLUENCE_API_TOKEN", "CONFLUENCE_SPACE_KEY"]:
            if not os.environ.get(key):
                missing.append(key)
        if missing:
            print(f"[ERROR] Missing environment variables: {', '.join(missing)}")
            sys.exit(1)

    def _parse_frontmatter(self, md_file):
        """Reads and parses the YAML frontmatter from the Markdown file.
        
        Returns (metadata_dict, rest_of_content).
        If no frontmatter, returns ({}, full_content).
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
                    print(f"[WARNING] Error parsing YAML frontmatter: {e}")
                    return {}, content
        return {}, content

    def _extract_title(self, md_file):
        """Extracts the title from the frontmatter or the first level 1 heading (#)."""
        metadata, _ = self._parse_frontmatter(md_file)
        
        # Priority 1: page_title in frontmatter
        if metadata.get("page_title"):
            return metadata["page_title"].strip()
        
        # Priority 2: first level 1 heading
        with open(md_file, "r", encoding="utf-8") as f:
            for line in f:
                stripped = line.strip()
                if stripped.startswith("# "):
                    return stripped[2:].strip()
        
        print("[WARNING] No title with '# ' found in the file. Using fallback.")
        return "Untitled document"

    def _verify_connection(self):
        """Verifies that the Confluence URL and space are valid."""
        print(f"[DEBUG] URL configured: {self.url}")
        print(f"[DEBUG] User: {self.user}")
        print(f"[DEBUG] Space Key: {self.space_key}")
        
        # Verify that the URL looks correct
        if not self.url.rstrip("/").endswith("/wiki"):
            print(f"[WARNING] The URL '{self.url}' does not end with '/wiki'. For Confluence Cloud, the URL is usually 'https://<domain>.atlassian.net/wiki'")
        
        # Test basic connectivity
        test_url = urljoin(self.url, "rest/api/space")
        print(f"[DEBUG] Testing connection to: {test_url}")
        try:
            resp = self.session.get(test_url, timeout=10)
            print(f"[DEBUG] Status code: {resp.status_code}")
            print(f"[DEBUG] Response: {resp.text[:500]}")
            if resp.status_code == 404:
                print(f"[ERROR] Cannot connect to Confluence at '{self.url}'. Verify that the URL is correct.")
                print(f"[ERROR] For Confluence Cloud, the URL should be something like: https://<your-domain>.atlassian.net/wiki")
                sys.exit(1)
            resp.raise_for_status()
        except requests.exceptions.RequestException as e:
            print(f"[ERROR] Cannot connect to Confluence: {e}")
            print(f"[ERROR] Verify that the URL '{self.url}' is correct and that you have access.")
            sys.exit(1)
        
        # Verify that the space exists
        space_url = urljoin(self.url, f"rest/api/space/{self.space_key}")
        print(f"[DEBUG] Verifying space: {space_url}")
        resp = self.session.get(space_url)
        print(f"[DEBUG] Space status code: {resp.status_code}")
        print(f"[DEBUG] Space response: {resp.text[:500]}")
        if resp.status_code == 404:
            print(f"[ERROR] The space '{self.space_key}' does not exist or you don't have permission to view it.")
            print(f"[ERROR] Verify that the space is correctly written in the CONFLUENCE_SPACE_KEY variable.")
            sys.exit(1)
        resp.raise_for_status()
        print(f"[INFO] Confluence connection OK. Space '{self.space_key}' verified.")

    def _convert_code_blocks(self, html_content):
        """Converts <pre><code> blocks to Confluence 'code' macro.
        Skips 'mermaid' blocks so they can be rendered as images later."""
        def replace_code(match):
            lang = match.group(1) or ""
            if lang == "mermaid":
                # Leave intact for _convert_mermaid_blocks to process later
                return match.group(0)
            code_text = match.group(2)
            # Unescape HTML entities so they look good in Confluence
            code_text = html.unescape(code_text)
            # Escape the CDATA delimiter if it appears in the code
            code_text = code_text.replace("]]>", "]]]]><![CDATA[>")
            return (
                f'<ac:structured-macro ac:name="code">'
                f'<ac:parameter ac:name="language">{lang}</ac:parameter>'
                f'<ac:plain-text-body><![CDATA[{code_text}]]></ac:plain-text-body>'
                f'</ac:structured-macro>'
            )
        
        # Replace all <pre><code class="language-xxx">...</code></pre> blocks
        pattern = r'<pre><code(?: class="language-([^"]*)")?>(.*?)</code></pre>'
        return re.sub(pattern, replace_code, html_content, flags=re.DOTALL)

    def _encode_mermaid_for_ink(self, diagram_source):
        """Encodes Mermaid diagram source for mermaid.ink API.

        mermaid.ink expects a JSON payload with editor state, compressed with
        full zlib (header + data + adler32) and base64url-encoded without padding.
        """
        payload = json.dumps(
            {
                "code": diagram_source,
                "mermaid": '{\n  "theme": "default"\n}',
                "updateEditor": True,
                "autoSync": True,
                "updateDiagram": True,
            },
            separators=(",", ":"),
        )
        compressed = zlib.compress(payload.encode("utf-8"), level=9)
        encoded = base64.urlsafe_b64encode(compressed).decode("ascii").rstrip("=")
        return f"pako:{encoded}"

    def _fetch_mermaid_image(self, encoded_diagram):
        """Fetches a PNG image from mermaid.ink for the encoded diagram."""
        url = f"https://mermaid.ink/img/{encoded_diagram}?type=png&bgColor=!white"
        resp = requests.get(url, timeout=30)
        resp.raise_for_status()
        return resp.content

    def _upload_attachment(self, page_id, filename, image_data, comment="Mermaid diagram"):
        """Uploads an image attachment to a Confluence page.

        If an attachment with the same filename already exists, it is deleted
        first so the new one can be created cleanly.
        """
        if self.dry_run:
            return {"id": "dry-run"}

        # Check if attachment already exists on this page
        search_url = urljoin(self.url, f"rest/api/content/{page_id}/child/attachment")
        params = {"filename": filename}
        resp = requests.get(search_url, auth=(self.user, self.token), params=params)
        if resp.status_code == 200:
            results = resp.json().get("results", [])
            if results:
                existing_id = results[0]["id"]
                print(f"[INFO] Existing attachment found: '{filename}' (ID: {existing_id}). Deleting...")
                delete_url = urljoin(self.url, f"rest/api/content/{existing_id}")
                del_resp = requests.delete(delete_url, auth=(self.user, self.token))
                if del_resp.status_code in (200, 204):
                    print(f"[INFO] Existing attachment deleted: '{filename}'")
                else:
                    print(f"[WARNING] Could not delete existing attachment '{filename}' (status: {del_resp.status_code})")

        # Create new attachment
        headers = {"X-Atlassian-Token": "no-check"}
        files = {"file": (filename, image_data, "image/png")}
        data = {"comment": comment}
        resp = requests.post(
            search_url,
            auth=(self.user, self.token),
            headers=headers,
            files=files,
            data=data,
        )
        resp.raise_for_status()
        print(f"[INFO] Attachment uploaded: '{filename}'")
        return resp.json()

    def _convert_mermaid_blocks(self, html_content, page_id):
        """Finds <pre><code class="language-mermaid"> blocks and replaces them with Confluence images."""
        if not page_id or page_id == "dry-run":
            return html_content

        def replace_mermaid(match):
            code_text = match.group(1)
            # Unescape HTML entities from markdown conversion
            code_text = html.unescape(code_text).strip()

            diagram_hash = hashlib.sha256(code_text.encode("utf-8")).hexdigest()[:12]
            filename = f"mermaid_{diagram_hash}.png"

            if self.dry_run:
                print(f"[DRY-RUN] Would generate Mermaid image: {filename}")
                return (
                    f'<ac:image ac:alt="Mermaid diagram">'
                    f'<ri:attachment ri:filename="{filename}" />'
                    f'</ac:image>'
                )

            try:
                encoded = self._encode_mermaid_for_ink(code_text)
                image_url = f"https://mermaid.ink/img/{encoded}?type=png&bgColor=!white"
                print(f"[DEBUG] Rendering Mermaid diagram: {image_url}")
                image_data = self._fetch_mermaid_image(encoded)
                self._upload_attachment(page_id, filename, image_data, comment="Auto-generated Mermaid diagram")
                print(f"[INFO] Mermaid diagram uploaded: {filename}")

                image_macro = (
                    f'<ac:image ac:alt="Mermaid diagram">'
                    f'<ri:attachment ri:filename="{filename}" />'
                    f'</ac:image>'
                )

                if not self.mermaid_show_source:
                    return image_macro

                escaped = code_text.replace("]]>", "]]]]><![CDATA[>")
                expand_macro = (
                    f'<ac:structured-macro ac:name="expand">'
                    f'<ac:parameter ac:name="title">Código fuente</ac:parameter>'
                    f'<ac:rich-text-body>'
                    f'<ac:structured-macro ac:name="code">'
                    f'<ac:parameter ac:name="language">mermaid</ac:parameter>'
                    f'<ac:plain-text-body><![CDATA[{escaped}]]></ac:plain-text-body>'
                    f'</ac:structured-macro>'
                    f'</ac:rich-text-body>'
                    f'</ac:structured-macro>'
                )
                return image_macro + expand_macro
            except Exception as e:
                print(f"[WARNING] Failed to render Mermaid diagram ({filename}): {e}")
                # Fallback: render as a Confluence code block
                escaped = code_text.replace("]]>", "]]]]><![CDATA[>")
                return (
                    f'<ac:structured-macro ac:name="code">'
                    f'<ac:parameter ac:name="language">mermaid</ac:parameter>'
                    f'<ac:plain-text-body><![CDATA[{escaped}]]></ac:plain-text-body>'
                    f'</ac:structured-macro>'
                )

        pattern = r'<pre><code class="language-mermaid">(.*?)</code></pre>'
        return re.sub(pattern, replace_mermaid, html_content, flags=re.DOTALL)

    def _md_to_html(self, md_file):
        with open(md_file, "r", encoding="utf-8") as f:
            text = f.read()
        # Convert markdown to HTML
        html_content = markdown.markdown(text, extensions=["tables", "fenced_code", "toc"])
        # Convert code blocks to Confluence macro
        html_content = self._convert_code_blocks(html_content)
        # Confluence requires the body to be wrapped in a storage macro if it's XHTML
        return f"<div>{html_content}</div>"

    def _request_with_retry(self, method, url, **kwargs):
        """Executes an HTTP request with automatic retries on 429 (rate limit)."""
        max_retries = 3
        for attempt in range(1, max_retries + 1):
            if self.dry_run:
                return None
            resp = self.session.request(method, url, **kwargs)
            if resp.status_code == 429:
                wait = 2 ** attempt  # exponential backoff: 2, 4, 8 sec
                print(f"[WARNING] Rate limit (429). Waiting {wait}s... (attempt {attempt}/{max_retries})")
                time.sleep(wait)
                continue
            resp.raise_for_status()
            return resp
        raise requests.exceptions.HTTPError("Persistent rate limit after 3 retries.")

    def _find_page(self, title=None, ancestor_id=None):
        """Searches for a page by title in the space. Optionally filters by ancestor."""
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
            # Disambiguate: prefer page that hangs from ancestor_id
            for r in results:
                ancestors = r.get("ancestors", [])
                if any(str(a.get("id")) == str(ancestor_id) for a in ancestors):
                    return r
        return results[0]

    def _create_page(self, html_content, title=None, parent_id=None):
        """Creates a new page in Confluence."""
        if self.dry_run:
            print(f"[DRY-RUN] Would create page: '{title}'")
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
        """Updates an existing page in Confluence."""
        if self.dry_run:
            print(f"[DRY-RUN] Would update page: '{title}' (ID: {page['id']})")
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
        """Searches for a page by title. If it exists, returns the ID. If not, creates it as a folder."""
        # Check cache first
        cache_key = f"{parent_id or 'root'}::{title}"
        if cache_key in self._folder_cache:
            cached_id = self._folder_cache[cache_key]
            print(f"[INFO] Folder found in cache: '{title}' (ID: {cached_id})")
            return cached_id

        page = self._find_page(title=title, ancestor_id=parent_id)
        if page:
            print(f"[INFO] Existing folder found: '{title}' (ID: {page['id']})")
            self._folder_cache[cache_key] = page["id"]
            return page["id"]

        # Create new page (folder)
        print(f"[INFO] Creating folder: '{title}'...")
        body = f'<div><p>Auto-generated folder: <strong>{title}</strong>.</p></div>'
        result = self._create_page(html_content=body, title=title, parent_id=parent_id)
        print(f"[SUCCESS] Folder created: '{title}' (ID: {result['id']})")
        self._folder_cache[cache_key] = result["id"]
        # Small pause to avoid rate limiting in mass creations
        time.sleep(0.3)
        return result["id"]

    def _sync_directory(self, dir_path, parent_id=None):
        """Processes a directory recursively, creating the folder structure in Confluence."""
        abs_path = os.path.abspath(dir_path)
        rel_path = os.path.relpath(abs_path, os.getcwd())

        # Determine parent_id for this folder
        folder_parent = parent_id if parent_id is not None else self.parent_id
        if folder_parent:
            folder_parent = int(folder_parent)

        # Create/obtain the page for this folder
        folder_title = os.path.basename(dir_path)
        try:
            folder_id = self._find_or_create_folder_page(folder_title, parent_id=folder_parent)
        except requests.exceptions.HTTPError as e:
            print(f"[ERROR] Failed to create/obtain folder '{folder_title}': {e}")
            raise

        # Traverse content (ignore hidden and symlinks)
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

        # Process subfolders first (so their children have IDs)
        for subdir in subdirs:
            current += 1
            subdir_path = os.path.join(dir_path, subdir)
            print(f"\n[{current}/{total_items}] Processing subfolder: {subdir}")
            self._sync_directory(subdir_path, parent_id=folder_id)

        # Process .md files
        for f in files:
            current += 1
            file_path = os.path.join(dir_path, f)
            print(f"\n[{current}/{total_items}] Processing file: {f}")
            self._sync_file(file_path, parent_id=folder_id)

    def _sync_file(self, file_path, parent_id=None):
        """Syncs an individual file, with optional parent_id."""
        page_title = self._extract_title(file_path)

        print(f"\n{'='*60}")
        print(f"[INFO] Syncing file: {file_path}")
        print(f"[INFO] Title: {page_title}")
        print(f"{'='*60}")

        # Read frontmatter metadata
        metadata, _ = self._parse_frontmatter(file_path)

        # Resolve confluence_id if it exists in frontmatter
        confluence_id = metadata.get("confluence_id")

        # Resolve parent_id if it exists in frontmatter (overrides the inherited one)
        frontmatter_parent_id = metadata.get("parent_id")
        if frontmatter_parent_id:
            parent_id = int(frontmatter_parent_id)
            print(f"[INFO] Using parent_id '{parent_id}' from frontmatter.")

        html_content = self._md_to_html(file_path)
        print(f"[INFO] Converting to HTML ({len(html_content)} chars)...")

        # Obtain the page (existing or new) so we have a page_id for attachments
        page = None
        is_new_page = False

        if confluence_id:
            print(f"[INFO] Using confluence_id '{confluence_id}' from frontmatter.")
            try:
                page_url = urljoin(self.url, f"rest/api/content/{confluence_id}")
                resp = self._request_with_retry("GET", page_url, params={"expand": "version,body.storage"})
                page = resp.json()
            except requests.exceptions.HTTPError as e:
                if e.response.status_code == 404:
                    print(f"[ERROR] The page with ID '{confluence_id}' was not found. Verify that the ID is correct.")
                    return
                raise
        else:
            print(f"[INFO] Searching for page '{page_title}' in space '{self.space_key}'...")
            page = self._find_page(title=page_title, ancestor_id=parent_id)
            if not page:
                print(f"[INFO] Page not found. Creating new...")
                placeholder = "<div><p>Initializing page content...</p></div>"
                page = self._create_page(placeholder, title=page_title, parent_id=parent_id)
                is_new_page = True
                print(f"[INFO] Page created (ID: {page['id']}). Processing content...")

        page_id = page["id"]

        # Convert Mermaid blocks to images and upload them as attachments
        final_html = self._convert_mermaid_blocks(html_content, page_id)

        # Update the page with the final HTML (images reference attachments by filename)
        result = self._update_page(page, final_html, title=page_title, parent_id=parent_id)
        action = "created" if is_new_page else "updated"
        print(f"[SUCCESS] Page {action}: {result['_links']['base']}{result['_links']['webui']}")

        # Small pause to avoid rate limiting
        time.sleep(0.3)

    def run(self, path):
        """Main method: decides whether to sync file or directory."""
        if not path:
            print("[ERROR] No file or directory specified.")
            sys.exit(1)
        
        if os.path.isdir(path):
            self._sync_directory(path)
        elif os.path.isfile(path):
            if not path.lower().endswith('.md'):
                print(f"[WARNING] The file '{path}' is not a .md. It will be skipped.")
                return
            self._sync_file(path)
        else:
            print(f"[ERROR] Path not found: {path}")
            sys.exit(1)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Sync Markdown files or directories to Confluence")
    parser.add_argument("paths", nargs="+", help="Markdown files or folders to sync")
    parser.add_argument("--dry-run", action="store_true", help="Simulates the execution without creating or updating pages in Confluence")
    args = parser.parse_args()

    errors = []
    # Create a single instance to reuse the connection
    sync = ConfluenceSync(dry_run=args.dry_run)
    
    for path in args.paths:
        print(f"\n{'='*60}")
        print(f"[INFO] Processing: {path}")
        if args.dry_run:
            print(f"[DRY-RUN] Simulation mode enabled. No changes will be made.")
        print(f"{'='*60}")
        try:
            if not os.path.exists(path):
                print(f"[ERROR] Path not found: {path}")
                errors.append(path)
                continue
            sync.run(path)
        except requests.exceptions.HTTPError as e:
            print(f"[ERROR] HTTP error in '{path}': {e}")
            if e.response is not None:
                print(f"[ERROR] Response: {e.response.text}")
            errors.append(path)
        except Exception as e:
            print(f"[ERROR] Error in '{path}': {e}")
            errors.append(path)

    if errors:
        print(f"\n[ERROR] {len(errors)} path(s) failed: {', '.join(errors)}")
        sys.exit(1)
    else:
        print(f"\n[SUCCESS] All paths processed successfully.")
