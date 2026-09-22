"""
FileStore — Persistent tracking, storage, and retrieval for received files.
"""

from __future__ import annotations

import os
import time
import mimetypes
import logging
import re
import json
import urllib.request
import urllib.parse
from pathlib import Path
from typing import Any

from store.database import Database

logger = logging.getLogger(__name__)

DOWNLOAD_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "downloads")
os.makedirs(DOWNLOAD_DIR, exist_ok=True)


class FileStore:
    """Manages received files: downloads, caches locally, and tracks in SQLite."""

    def __init__(self, db: Database, download_dir: str = DOWNLOAD_DIR):
        self.db = db
        self.download_dir = download_dir
        os.makedirs(self.download_dir, exist_ok=True)

    def record_file(
        self,
        *,
        file_id: str,
        file_name: str,
        file_size: int = 0,
        mime_type: str = "",
        frontend: str = "",
        group_id: str = "",
        user_id: str = "",
        message_id: str = "",
        local_path: str = "",
        url: str = "",
        created_at: float | None = None,
    ) -> int:
        """Insert or update a received file record in the database."""
        now = created_at if created_at is not None else time.time()
        conn = self.db.get_conn()
        cur = conn.execute(
            """
            INSERT INTO files (
                file_id, file_name, file_size, mime_type, frontend,
                group_id, user_id, message_id, local_path, url, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                str(file_id),
                str(file_name),
                int(file_size),
                str(mime_type),
                str(frontend),
                str(group_id),
                str(user_id),
                str(message_id),
                str(local_path),
                str(url),
                now,
            ),
        )
        conn.commit()
        return cur.lastrowid

    def get_file(self, file_db_id: int) -> dict | None:
        """Retrieve a file record by its database primary key ID."""
        conn = self.db.get_conn()
        cur = conn.execute("SELECT * FROM files WHERE id = ?", (file_db_id,))
        row = cur.fetchone()
        return dict(row) if row else None

    def get_files_by_message(self, message_id: str) -> list[dict]:
        """Retrieve all files associated with a specific message_id."""
        if not message_id:
            return []
        conn = self.db.get_conn()
        cur = conn.execute(
            "SELECT * FROM files WHERE message_id = ? ORDER BY id ASC",
            (str(message_id),),
        )
        return [dict(row) for row in cur.fetchall()]

    def get_recent_files(
        self,
        *,
        frontend: str = "",
        group_id: str = "",
        user_id: str = "",
        limit: int = 5,
        max_age_seconds: float = 86400.0,
    ) -> list[dict]:
        """
        Retrieve recent files for a group or direct message scope within max_age_seconds.
        """
        cutoff = time.time() - max_age_seconds
        conn = self.db.get_conn()
        if group_id:
            cur = conn.execute(
                """
                SELECT * FROM files 
                WHERE group_id = ? AND created_at >= ?
                ORDER BY created_at DESC LIMIT ?
                """,
                (str(group_id), cutoff, limit),
            )
        elif user_id:
            cur = conn.execute(
                """
                SELECT * FROM files 
                WHERE user_id = ? AND created_at >= ?
                ORDER BY created_at DESC LIMIT ?
                """,
                (str(user_id), cutoff, limit),
            )
        else:
            cur = conn.execute(
                "SELECT * FROM files WHERE created_at >= ? ORDER BY created_at DESC LIMIT ?",
                (cutoff, limit),
            )
        return [dict(row) for row in cur.fetchall()]

    def find_file(
        self,
        query: str,
        *,
        group_id: str = "",
        user_id: str = "",
    ) -> dict | None:
        """
        Fuzzy search for a file by ID (integer primary key or file_id) or file name substring.
        """
        conn = self.db.get_conn()
        query = query.strip()
        if not query:
            return None

        # 1. Exact DB ID match
        if query.isdigit():
            cur = conn.execute("SELECT * FROM files WHERE id = ?", (int(query),))
            row = cur.fetchone()
            if row:
                return dict(row)

        # 2. Exact file_id match
        cur = conn.execute("SELECT * FROM files WHERE file_id = ? ORDER BY id DESC LIMIT 1", (query,))
        row = cur.fetchone()
        if row:
            return dict(row)

        # 3. Exact or prefix file_name match in current scope
        if group_id:
            cur = conn.execute(
                """
                SELECT * FROM files 
                WHERE group_id = ? AND (file_name = ? OR file_name LIKE ?)
                ORDER BY id DESC LIMIT 1
                """,
                (str(group_id), query, f"%{query}%"),
            )
            row = cur.fetchone()
            if row:
                return dict(row)

        # 4. Global fallback
        cur = conn.execute(
            """
            SELECT * FROM files 
            WHERE file_name = ? OR file_name LIKE ?
            ORDER BY id DESC LIMIT 1
            """,
            (query, f"%{query}%"),
        )
        row = cur.fetchone()
        return dict(row) if row else None

    def save_and_record_file(
        self,
        file_info: dict,
        *,
        frontend: str,
        group_id: str = "",
        user_id: str = "",
        message_id: str = "",
    ) -> dict:
        """
        Processes an incoming file dict (from request.files or adapters):
        - Resolves local file path or downloads remote URL into data/downloads
        - Guarantees mime_type and file_size
        - Records in SQLite files table
        Returns the recorded file dict with 'id' and 'local_path'.
        """
        file_name = file_info.get("file_name") or file_info.get("name") or "unknown_file"
        file_id = str(file_info.get("file_id") or file_info.get("id") or "")
        url = str(file_info.get("url") or "")
        raw_path = str(file_info.get("path") or file_info.get("local_path") or "")
        mime_type = str(file_info.get("mime_type") or "")
        file_size = int(file_info.get("file_size") or file_info.get("size") or 0)

        # Resolve local path if path is a file:// URI
        local_target_path = ""
        if raw_path:
            if raw_path.startswith("file:///"):
                clean = raw_path[8:] if os.name == "nt" else raw_path[7:]
                local_target_path = urllib.parse.unquote(clean)
            elif raw_path.startswith("file://"):
                local_target_path = urllib.parse.unquote(raw_path[7:])
            elif os.path.exists(raw_path):
                local_target_path = raw_path

        # Extract filename from URL query params or path if file_name is unknown
        if (not file_name or file_name == "unknown_file") and url:
            try:
                parsed_url = urllib.parse.urlparse(url)
                qs = urllib.parse.parse_qs(parsed_url.query)
                if "fname" in qs and qs["fname"]:
                    file_name = qs["fname"][0]
                elif parsed_url.path:
                    base = os.path.basename(parsed_url.path)
                    if "." in base:
                        file_name = base
            except Exception:
                pass

        # If we have a local path that exists, use it
        if local_target_path and os.path.exists(local_target_path):
            try:
                file_size = os.path.getsize(local_target_path)
            except Exception:
                pass
        elif url:
            # Download to local download_dir if it's an HTTP/HTTPS URL
            try:
                # Deduce extension
                ext = os.path.splitext(file_name)[1]
                if not ext and "." in url:
                    parsed_url_path = urllib.parse.urlparse(url).path
                    ext = os.path.splitext(parsed_url_path)[1]
                clean_fid = re.sub(r'[^\w\-.]', '_', file_id.strip())
                safe_name = f"{int(time.time())}_{clean_fid or 'file'}{ext}"
                dest = os.path.join(self.download_dir, safe_name)
                
                logger.info("[FileStore] Downloading remote file '%s' from %s", file_name, url[:120])
                t_start = time.time()
                req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"})
                with urllib.request.urlopen(req, timeout=60.0) as response, open(dest, "wb") as out_file:
                    out_file.write(response.read())
                
                local_target_path = os.path.abspath(dest)
                file_size = os.path.getsize(local_target_path)
                logger.info(
                    "[FileStore] Downloaded '%s' (%d bytes) in %.2fs -> %s",
                    file_name, file_size, time.time() - t_start, local_target_path
                )
            except Exception as e:
                logger.warning("[FileStore] Failed to download remote file '%s' from %s: %s", file_name, url, e)

        # Fallback mime detection
        if not mime_type and (file_name or local_target_path):
            guess_name = file_name or local_target_path
            guessed, _ = mimetypes.guess_type(guess_name)
            if guessed:
                mime_type = guessed

        rec_id = self.record_file(
            file_id=file_id or os.path.basename(local_target_path or file_name),
            file_name=file_name,
            file_size=file_size,
            mime_type=mime_type,
            frontend=frontend,
            group_id=group_id,
            user_id=user_id,
            message_id=message_id,
            local_path=local_target_path,
            url=url,
        )

        return {
            "id": rec_id,
            "file_id": file_id,
            "file_name": file_name,
            "file_size": file_size,
            "mime_type": mime_type,
            "frontend": frontend,
            "group_id": group_id,
            "user_id": user_id,
            "message_id": message_id,
            "local_path": local_target_path,
            "url": url,
        }

    def ensure_local_file(self, file_rec: dict) -> str:
        """
        Ensures a file record is downloaded to a local disk path.
        If local_path exists, returns it.
        If local_path does not exist:
          - Tries to download using 'url'.
          - If 'url' is missing and frontend is onebot/cqhttp with group_id and file_id:
            Tries to query http://127.0.0.1:5700/get_group_file_url.
        Updates SQLite files record if successfully resolved/downloaded.
        Returns the resolved local_path or empty string on failure.
        """
        if not file_rec or not isinstance(file_rec, dict):
            return ""

        local_path = file_rec.get("local_path", "")
        if local_path and os.path.exists(local_path):
            return local_path

        rec_id = file_rec.get("id")
        url = str(file_rec.get("url") or "").strip()
        file_id = str(file_rec.get("file_id") or "").strip()
        group_id = str(file_rec.get("group_id") or "").strip()
        frontend = str(file_rec.get("frontend") or "").strip()
        file_name = str(file_rec.get("file_name") or "") or "unknown_file"

        # If URL is missing, check if we can query OneBot API
        if not url and frontend in ("onebot", "cqhttp") and group_id and file_id:
            try:
                req_data = json.dumps({"group_id": int(group_id), "file_id": file_id}).encode("utf-8")
                req = urllib.request.Request(
                    "http://127.0.0.1:5700/get_group_file_url",
                    data=req_data,
                    headers={"Content-Type": "application/json"},
                )
                with urllib.request.urlopen(req, timeout=5.0) as resp:
                    resp_json = json.loads(resp.read().decode("utf-8"))
                    url = resp_json.get("data", {}).get("url", "")
            except Exception as e:
                logger.warning("ensure_local_file: failed to get group file url from OneBot API: %s", e)

        if not url:
            return ""

        # Extract file_name from url if unknown
        if (not file_name or file_name == "unknown_file") and url:
            try:
                parsed_url = urllib.parse.urlparse(url)
                qs = urllib.parse.parse_qs(parsed_url.query)
                if "fname" in qs and qs["fname"]:
                    file_name = qs["fname"][0]
                elif parsed_url.path:
                    base = os.path.basename(parsed_url.path)
                    if "." in base:
                        file_name = base
            except Exception:
                pass

        try:
            ext = os.path.splitext(file_name)[1]
            if not ext and "." in url:
                parsed_url_path = urllib.parse.urlparse(url).path
                ext = os.path.splitext(parsed_url_path)[1]

            clean_fid = re.sub(r'[^\w\-.]', '_', file_id.strip())
            safe_name = f"{int(time.time())}_{clean_fid or 'file'}{ext}"
            dest = os.path.join(self.download_dir, safe_name)

            logger.info("[FileStore:ensure_local_file] Downloading missing file '%s' from %s", file_name, url[:120])
            t_start = time.time()
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"})
            with urllib.request.urlopen(req, timeout=60.0) as response, open(dest, "wb") as out_file:
                out_file.write(response.read())

            downloaded_path = os.path.abspath(dest)
            file_size = os.path.getsize(downloaded_path)
            guessed_mime, _ = mimetypes.guess_type(downloaded_path)

            file_rec["local_path"] = downloaded_path
            file_rec["file_name"] = file_name
            file_rec["file_size"] = file_size
            file_rec["url"] = url
            if guessed_mime:
                file_rec["mime_type"] = guessed_mime

            # Update DB if rec_id exists
            if rec_id:
                conn = self.db.get_conn()
                conn.execute(
                    """
                    UPDATE files 
                    SET local_path = ?, file_name = ?, file_size = ?, url = ?, mime_type = ?
                    WHERE id = ?
                    """,
                    (downloaded_path, file_name, file_size, url, file_rec.get("mime_type", ""), rec_id),
                )
                conn.commit()

            logger.info(
                "[FileStore:ensure_local_file] Successfully downloaded '%s' (%d bytes) in %.2fs -> %s",
                file_name, file_size, time.time() - t_start, downloaded_path
            )
            return downloaded_path
        except Exception as e:
            logger.warning("[FileStore:ensure_local_file] Failed downloading '%s' from %s: %s", file_name, url, e)
            return ""
