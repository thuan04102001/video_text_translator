import json
import os
import re
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path

import requests


BASE_DIR = Path(__file__).resolve().parents[2]
DATA_DIR = BASE_DIR / "data"
DB_PATH = DATA_DIR / "auto_reup.sqlite3"
GRAPH_API_VERSION = os.getenv("META_GRAPH_VERSION", "v20.0").strip() or "v20.0"

URL_RE = re.compile(
    r"(?i)(?:https?://|www\.)\S+|"
    r"\b[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?"
    r"\.(?:com|net|org|io|co|me|ly|vn|info|biz|shop|store|site|online|xyz|app|tv|gg|cc|link)\S*"
)

AFFILIATE_CTA_RE = re.compile(
    r"(?i)\b("
    r"affiliate|aff(?:iliate)?\s*link|link\s*in\s*bio|click\s*link|buy\s*now|"
    r"shop\s*(?:now|here)|order\s*(?:now|here)|coupon|promo\s*code|discount\s*code|"
    r"use\s*code|dm\s*me|inbox\s*me|bio\s*link|link\s*below"
    r")\b"
)


def _now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _new_id():
    return uuid.uuid4().hex


def _connect():
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def _decode_json(value, fallback):
    if not value:
        return fallback
    try:
        return json.loads(value)
    except Exception:
        return fallback


def _row_to_dict(row):
    data = dict(row)
    for key in ["removed_links", "removed_lines"]:
        if key in data:
            data[key] = _decode_json(data[key], [])
    if "meta_tasks" in data:
        data["meta_tasks"] = _decode_json(data["meta_tasks"], [])
    if "page_access_token" in data:
        data["has_page_access_token"] = bool(data.get("page_access_token"))
        data.pop("page_access_token", None)
    for key in ["is_enabled", "enabled", "translate_caption", "apply_frame", "content_cleaner_enabled"]:
        if key in data:
            data[key] = bool(data[key])
    return data


def _ensure_columns(conn, table_name, column_defs):
    existing = {
        row["name"]
        for row in conn.execute(f"PRAGMA table_info({table_name})").fetchall()
    }
    for column_name, column_def in column_defs.items():
        if column_name not in existing:
            conn.execute(f"ALTER TABLE {table_name} ADD COLUMN {column_name} {column_def}")


def init_auto_reup_db():
    with _connect() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS fanpages (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                page_id TEXT,
                access_status TEXT NOT NULL DEFAULT 'not_connected',
                is_enabled INTEGER NOT NULL DEFAULT 0,
                daily_limit INTEGER NOT NULL DEFAULT 3,
                active_from TEXT NOT NULL DEFAULT '09:00',
                active_to TEXT NOT NULL DEFAULT '22:30',
                min_gap_minutes INTEGER NOT NULL DEFAULT 180,
                default_template_id TEXT,
                notes TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS reup_sources (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                platform TEXT NOT NULL,
                source_url TEXT NOT NULL,
                target_page_id TEXT,
                template_id TEXT,
                translate_caption INTEGER NOT NULL DEFAULT 1,
                apply_frame INTEGER NOT NULL DEFAULT 0,
                enabled INTEGER NOT NULL DEFAULT 1,
                scan_interval_minutes INTEGER NOT NULL DEFAULT 60,
                last_scan_at TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                FOREIGN KEY(target_page_id) REFERENCES fanpages(id)
            );

            CREATE TABLE IF NOT EXISTS reup_jobs (
                id TEXT PRIMARY KEY,
                source_id TEXT,
                target_page_id TEXT,
                source_post_id TEXT,
                source_video_url TEXT,
                raw_content TEXT,
                clean_content TEXT,
                removed_links TEXT,
                removed_lines TEXT,
                status TEXT NOT NULL DEFAULT 'queued',
                scheduled_at TEXT,
                posted_at TEXT,
                error TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                FOREIGN KEY(source_id) REFERENCES reup_sources(id),
                FOREIGN KEY(target_page_id) REFERENCES fanpages(id)
            );

            CREATE TABLE IF NOT EXISTS reup_actions (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                target_page_id TEXT,
                platform TEXT NOT NULL DEFAULT 'facebook',
                source_url TEXT NOT NULL,
                template_id TEXT,
                translate_caption INTEGER NOT NULL DEFAULT 1,
                apply_frame INTEGER NOT NULL DEFAULT 0,
                content_cleaner_enabled INTEGER NOT NULL DEFAULT 1,
                enabled INTEGER NOT NULL DEFAULT 1,
                daily_limit INTEGER NOT NULL DEFAULT 3,
                active_from TEXT NOT NULL DEFAULT '09:00',
                active_to TEXT NOT NULL DEFAULT '22:30',
                min_gap_minutes INTEGER NOT NULL DEFAULT 180,
                scan_interval_minutes INTEGER NOT NULL DEFAULT 60,
                progress_total INTEGER NOT NULL DEFAULT 0,
                progress_scanned INTEGER NOT NULL DEFAULT 0,
                progress_posted INTEGER NOT NULL DEFAULT 0,
                progress_errors INTEGER NOT NULL DEFAULT 0,
                last_scan_at TEXT,
                notes TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                FOREIGN KEY(target_page_id) REFERENCES fanpages(id)
            );
            """
        )
        _ensure_columns(
            conn,
            "fanpages",
            {
                "page_access_token": "TEXT",
                "meta_tasks": "TEXT",
                "meta_category": "TEXT",
                "connected_at": "TEXT",
                "token_source": "TEXT",
                "token_last_checked_at": "TEXT",
            },
        )
        conn.commit()


def clean_post_content(content):
    raw = str(content or "").replace("\r\n", "\n").replace("\r", "\n")
    removed_links = []
    removed_lines = []
    cleaned_lines = []

    for line in raw.split("\n"):
        original_line = line.strip()
        if not original_line:
            if cleaned_lines and cleaned_lines[-1] != "":
                cleaned_lines.append("")
            continue

        line_links = [match.group(0).rstrip(").,;!?]") for match in URL_RE.finditer(original_line)]
        removed_links.extend(line_links)
        without_links = URL_RE.sub("", original_line)
        without_links = re.sub(r"\s{2,}", " ", without_links).strip(" -|.,")

        if line_links and (not without_links or AFFILIATE_CTA_RE.search(original_line)):
            removed_lines.append(original_line)
            continue

        if AFFILIATE_CTA_RE.search(without_links) and len(without_links.split()) <= 8:
            removed_lines.append(original_line)
            continue

        if without_links:
            cleaned_lines.append(without_links)

    clean_content = "\n".join(cleaned_lines).strip()
    clean_content = re.sub(r"\n{3,}", "\n\n", clean_content)

    unique_links = []
    for link in removed_links:
        if link not in unique_links:
            unique_links.append(link)

    return {
        "raw_content": raw,
        "clean_content": clean_content,
        "removed_links": unique_links,
        "removed_lines": removed_lines,
        "has_removed_links": bool(unique_links),
    }


def summary():
    init_auto_reup_db()
    with _connect() as conn:
        page_total = conn.execute("SELECT COUNT(*) FROM fanpages").fetchone()[0]
        page_active = conn.execute(
            "SELECT COUNT(*) FROM fanpages WHERE is_enabled = 1"
        ).fetchone()[0]
        source_total = conn.execute("SELECT COUNT(*) FROM reup_sources").fetchone()[0]
        source_active = conn.execute(
            "SELECT COUNT(*) FROM reup_sources WHERE enabled = 1"
        ).fetchone()[0]
        action_total = conn.execute("SELECT COUNT(*) FROM reup_actions").fetchone()[0]
        action_active = conn.execute(
            "SELECT COUNT(*) FROM reup_actions WHERE enabled = 1"
        ).fetchone()[0]
        queued = conn.execute(
            "SELECT COUNT(*) FROM reup_jobs WHERE status = 'queued'"
        ).fetchone()[0]
        processing = conn.execute(
            "SELECT COUNT(*) FROM reup_jobs WHERE status = 'processing'"
        ).fetchone()[0]
        posted = conn.execute(
            "SELECT COUNT(*) FROM reup_jobs WHERE status = 'posted'"
        ).fetchone()[0]
        errors = conn.execute(
            "SELECT COUNT(*) FROM reup_jobs WHERE status = 'error'"
        ).fetchone()[0]
        connected_pages = conn.execute(
            """
            SELECT COUNT(*)
            FROM fanpages
            WHERE access_status = 'connected'
              AND COALESCE(page_access_token, '') != ''
            """
        ).fetchone()[0]

    return {
        "fanpages": page_total,
        "active_pages": page_active,
        "sources": source_total,
        "active_sources": source_active,
        "actions": action_total,
        "active_actions": action_active,
        "queued": queued,
        "processing": processing,
        "posted": posted,
        "errors": errors,
        "publish_status": "meta_connected" if connected_pages else "waiting_for_meta_api",
    }


def list_pages():
    init_auto_reup_db()
    with _connect() as conn:
        rows = conn.execute(
            "SELECT * FROM fanpages ORDER BY created_at DESC"
        ).fetchall()
    return [_row_to_dict(row) for row in rows]


def create_page(payload):
    init_auto_reup_db()
    now = _now()
    data = {
        "id": _new_id(),
        "name": payload.get("name", "").strip(),
        "page_id": payload.get("page_id", "").strip(),
        "access_status": payload.get("access_status") or "not_connected",
        "is_enabled": 1 if payload.get("is_enabled") else 0,
        "daily_limit": int(payload.get("daily_limit") or 3),
        "active_from": payload.get("active_from") or "09:00",
        "active_to": payload.get("active_to") or "22:30",
        "min_gap_minutes": int(payload.get("min_gap_minutes") or 180),
        "default_template_id": payload.get("default_template_id") or "",
        "notes": payload.get("notes") or "",
        "page_access_token": payload.get("page_access_token") or "",
        "meta_tasks": json.dumps(payload.get("meta_tasks") or [], ensure_ascii=False),
        "meta_category": payload.get("meta_category") or "",
        "connected_at": payload.get("connected_at") or None,
        "token_source": payload.get("token_source") or "",
        "token_last_checked_at": payload.get("token_last_checked_at") or None,
        "created_at": now,
        "updated_at": now,
    }

    if not data["name"]:
        raise ValueError("Missing page name")

    with _connect() as conn:
        conn.execute(
            """
            INSERT INTO fanpages (
                id, name, page_id, access_status, is_enabled, daily_limit,
                active_from, active_to, min_gap_minutes, default_template_id,
                notes, page_access_token, meta_tasks, meta_category, connected_at,
                token_source, token_last_checked_at, created_at, updated_at
            ) VALUES (
                :id, :name, :page_id, :access_status, :is_enabled, :daily_limit,
                :active_from, :active_to, :min_gap_minutes, :default_template_id,
                :notes, :page_access_token, :meta_tasks, :meta_category, :connected_at,
                :token_source, :token_last_checked_at, :created_at, :updated_at
            )
            """,
            data,
        )
        conn.commit()

    return get_page(data["id"])


def get_page(page_id):
    init_auto_reup_db()
    with _connect() as conn:
        row = conn.execute(
            "SELECT * FROM fanpages WHERE id = ?",
            (page_id,),
        ).fetchone()
    if not row:
        raise ValueError("Fanpage not found")
    return _row_to_dict(row)


def update_page(page_id, payload):
    init_auto_reup_db()
    allowed = {
        "name",
        "page_id",
        "access_status",
        "is_enabled",
        "daily_limit",
        "active_from",
        "active_to",
        "min_gap_minutes",
        "default_template_id",
        "notes",
        "page_access_token",
        "meta_tasks",
        "meta_category",
        "connected_at",
        "token_source",
        "token_last_checked_at",
    }
    updates = {key: value for key, value in payload.items() if key in allowed}
    if not updates:
        return get_page(page_id)

    if "is_enabled" in updates:
        updates["is_enabled"] = 1 if updates["is_enabled"] else 0

    for numeric_key in ["daily_limit", "min_gap_minutes"]:
        if numeric_key in updates and updates[numeric_key] is not None:
            updates[numeric_key] = int(updates[numeric_key])

    if "meta_tasks" in updates and not isinstance(updates["meta_tasks"], str):
        updates["meta_tasks"] = json.dumps(updates["meta_tasks"] or [], ensure_ascii=False)

    updates["updated_at"] = _now()
    assignments = ", ".join([f"{key} = :{key}" for key in updates])
    updates["id"] = page_id

    with _connect() as conn:
        conn.execute(f"UPDATE fanpages SET {assignments} WHERE id = :id", updates)
        conn.commit()

    return get_page(page_id)


def _graph_get(path, access_token, params=None, graph_version=None):
    token = str(access_token or "").strip()
    if not token:
        raise ValueError("Missing Meta access token")

    version = (graph_version or GRAPH_API_VERSION).strip().strip("/")
    url = f"https://graph.facebook.com/{version}/{path.lstrip('/')}"
    query = dict(params or {})
    query["access_token"] = token

    try:
        response = requests.get(url, params=query, timeout=25)
        payload = response.json()
    except requests.RequestException as error:
        raise ValueError(f"Meta API connection failed: {error}") from error
    except ValueError as error:
        raise ValueError("Meta API returned invalid JSON") from error

    if response.status_code >= 400 or "error" in payload:
        meta_error = payload.get("error") if isinstance(payload, dict) else None
        message = meta_error.get("message") if isinstance(meta_error, dict) else response.text
        raise ValueError(f"Meta API error: {message}")

    return payload


def _sanitize_meta_page(page, include_token=False):
    tasks = page.get("tasks") or []
    data = {
        "page_id": str(page.get("id") or ""),
        "name": page.get("name") or "",
        "meta_category": page.get("category") or "",
        "meta_tasks": tasks if isinstance(tasks, list) else [],
        "has_page_access_token": bool(page.get("access_token")),
    }
    if include_token:
        data["page_access_token"] = page.get("access_token") or ""
    return data


def fetch_meta_pages(access_token, graph_version=None):
    fields = "id,name,access_token,tasks,category"
    pages = []
    payload = _graph_get(
        "me/accounts",
        access_token,
        {"fields": fields, "limit": 100},
        graph_version=graph_version,
    )

    for _ in range(10):
        pages.extend(_sanitize_meta_page(page) for page in payload.get("data", []))
        next_url = payload.get("paging", {}).get("next")
        if not next_url:
            break
        try:
            response = requests.get(next_url, timeout=25)
            payload = response.json()
        except requests.RequestException as error:
            raise ValueError(f"Meta API paging failed: {error}") from error
        except ValueError as error:
            raise ValueError("Meta API returned invalid JSON while paging") from error

        if response.status_code >= 400 or "error" in payload:
            meta_error = payload.get("error") if isinstance(payload, dict) else None
            message = meta_error.get("message") if isinstance(meta_error, dict) else response.text
            raise ValueError(f"Meta API error: {message}")

    return {"pages": pages, "count": len(pages)}


def import_meta_pages(access_token, graph_version=None):
    fields = "id,name,access_token,tasks,category"
    payload = _graph_get(
        "me/accounts",
        access_token,
        {"fields": fields, "limit": 100},
        graph_version=graph_version,
    )

    raw_pages = []
    for _ in range(10):
        raw_pages.extend(payload.get("data", []))
        next_url = payload.get("paging", {}).get("next")
        if not next_url:
            break
        try:
            response = requests.get(next_url, timeout=25)
            payload = response.json()
        except requests.RequestException as error:
            raise ValueError(f"Meta API paging failed: {error}") from error
        except ValueError as error:
            raise ValueError("Meta API returned invalid JSON while paging") from error

        if response.status_code >= 400 or "error" in payload:
            meta_error = payload.get("error") if isinstance(payload, dict) else None
            message = meta_error.get("message") if isinstance(meta_error, dict) else response.text
            raise ValueError(f"Meta API error: {message}")

    init_auto_reup_db()
    now = _now()
    imported = 0
    updated = 0
    imported_pages = []

    with _connect() as conn:
        for raw_page in raw_pages:
            page = _sanitize_meta_page(raw_page, include_token=True)
            if not page["page_id"] or not page["name"]:
                continue

            existing = conn.execute(
                "SELECT id FROM fanpages WHERE page_id = ?",
                (page["page_id"],),
            ).fetchone()
            data = {
                "id": existing["id"] if existing else _new_id(),
                "name": page["name"],
                "page_id": page["page_id"],
                "access_status": "connected" if page["page_access_token"] else "missing_page_token",
                "is_enabled": 1,
                "daily_limit": 3,
                "active_from": "09:00",
                "active_to": "22:30",
                "min_gap_minutes": 180,
                "default_template_id": "",
                "notes": "",
                "page_access_token": page["page_access_token"],
                "meta_tasks": json.dumps(page["meta_tasks"], ensure_ascii=False),
                "meta_category": page["meta_category"],
                "connected_at": now,
                "token_source": "meta_import",
                "token_last_checked_at": now,
                "created_at": now,
                "updated_at": now,
            }

            if existing:
                conn.execute(
                    """
                    UPDATE fanpages
                    SET name = :name,
                        page_id = :page_id,
                        access_status = :access_status,
                        is_enabled = :is_enabled,
                        page_access_token = :page_access_token,
                        meta_tasks = :meta_tasks,
                        meta_category = :meta_category,
                        connected_at = :connected_at,
                        token_source = :token_source,
                        token_last_checked_at = :token_last_checked_at,
                        updated_at = :updated_at
                    WHERE id = :id
                    """,
                    data,
                )
                updated += 1
            else:
                conn.execute(
                    """
                    INSERT INTO fanpages (
                        id, name, page_id, access_status, is_enabled, daily_limit,
                        active_from, active_to, min_gap_minutes, default_template_id,
                        notes, page_access_token, meta_tasks, meta_category,
                        connected_at, token_source, token_last_checked_at,
                        created_at, updated_at
                    ) VALUES (
                        :id, :name, :page_id, :access_status, :is_enabled, :daily_limit,
                        :active_from, :active_to, :min_gap_minutes, :default_template_id,
                        :notes, :page_access_token, :meta_tasks, :meta_category,
                        :connected_at, :token_source, :token_last_checked_at,
                        :created_at, :updated_at
                    )
                    """,
                    data,
                )
                imported += 1

            row = conn.execute("SELECT * FROM fanpages WHERE id = ?", (data["id"],)).fetchone()
            imported_pages.append(_row_to_dict(row))

        conn.commit()

    return {
        "imported": imported,
        "updated": updated,
        "pages": imported_pages,
        "count": len(imported_pages),
    }


def delete_page(page_id):
    init_auto_reup_db()
    with _connect() as conn:
        conn.execute("UPDATE reup_sources SET target_page_id = NULL WHERE target_page_id = ?", (page_id,))
        conn.execute("UPDATE reup_jobs SET target_page_id = NULL WHERE target_page_id = ?", (page_id,))
        conn.execute("UPDATE reup_actions SET target_page_id = NULL WHERE target_page_id = ?", (page_id,))
        deleted = conn.execute("DELETE FROM fanpages WHERE id = ?", (page_id,)).rowcount
        conn.commit()

    if not deleted:
        raise ValueError("Fanpage not found")
    return {"id": page_id}


def list_sources():
    init_auto_reup_db()
    with _connect() as conn:
        rows = conn.execute(
            """
            SELECT s.*, p.name AS target_page_name
            FROM reup_sources s
            LEFT JOIN fanpages p ON p.id = s.target_page_id
            ORDER BY s.created_at DESC
            """
        ).fetchall()
    return [_row_to_dict(row) for row in rows]


def create_source(payload):
    init_auto_reup_db()
    now = _now()
    data = {
        "id": _new_id(),
        "name": payload.get("name", "").strip(),
        "platform": (payload.get("platform") or "facebook").strip(),
        "source_url": payload.get("source_url", "").strip(),
        "target_page_id": payload.get("target_page_id") or None,
        "template_id": payload.get("template_id") or "",
        "translate_caption": 1 if payload.get("translate_caption", True) else 0,
        "apply_frame": 1 if payload.get("apply_frame") else 0,
        "enabled": 1 if payload.get("enabled", True) else 0,
        "scan_interval_minutes": int(payload.get("scan_interval_minutes") or 60),
        "last_scan_at": None,
        "created_at": now,
        "updated_at": now,
    }

    if not data["name"]:
        raise ValueError("Missing source name")
    if not data["source_url"]:
        raise ValueError("Missing source URL")

    with _connect() as conn:
        conn.execute(
            """
            INSERT INTO reup_sources (
                id, name, platform, source_url, target_page_id, template_id,
                translate_caption, apply_frame, enabled, scan_interval_minutes,
                last_scan_at, created_at, updated_at
            ) VALUES (
                :id, :name, :platform, :source_url, :target_page_id, :template_id,
                :translate_caption, :apply_frame, :enabled, :scan_interval_minutes,
                :last_scan_at, :created_at, :updated_at
            )
            """,
            data,
        )
        conn.commit()

    return get_source(data["id"])


def get_source(source_id):
    with _connect() as conn:
        row = conn.execute(
            """
            SELECT s.*, p.name AS target_page_name
            FROM reup_sources s
            LEFT JOIN fanpages p ON p.id = s.target_page_id
            WHERE s.id = ?
            """,
            (source_id,),
        ).fetchone()
    if not row:
        raise ValueError("Source not found")
    return _row_to_dict(row)


def update_source(source_id, payload):
    init_auto_reup_db()
    allowed = {
        "name",
        "platform",
        "source_url",
        "target_page_id",
        "template_id",
        "translate_caption",
        "apply_frame",
        "enabled",
        "scan_interval_minutes",
        "last_scan_at",
    }
    updates = {key: value for key, value in payload.items() if key in allowed}
    if not updates:
        return get_source(source_id)

    for boolean_key in ["translate_caption", "apply_frame", "enabled"]:
        if boolean_key in updates:
            updates[boolean_key] = 1 if updates[boolean_key] else 0

    if "scan_interval_minutes" in updates and updates["scan_interval_minutes"] is not None:
        updates["scan_interval_minutes"] = int(updates["scan_interval_minutes"])

    updates["updated_at"] = _now()
    assignments = ", ".join([f"{key} = :{key}" for key in updates])
    updates["id"] = source_id

    with _connect() as conn:
        conn.execute(f"UPDATE reup_sources SET {assignments} WHERE id = :id", updates)
        conn.commit()

    return get_source(source_id)


def delete_source(source_id):
    init_auto_reup_db()
    with _connect() as conn:
        conn.execute("UPDATE reup_jobs SET source_id = NULL WHERE source_id = ?", (source_id,))
        deleted = conn.execute("DELETE FROM reup_sources WHERE id = ?", (source_id,)).rowcount
        conn.commit()

    if not deleted:
        raise ValueError("Source not found")
    return {"id": source_id}


def list_actions():
    init_auto_reup_db()
    with _connect() as conn:
        rows = conn.execute(
            """
            SELECT a.*, p.name AS target_page_name, p.page_id AS target_page_external_id
            FROM reup_actions a
            LEFT JOIN fanpages p ON p.id = a.target_page_id
            ORDER BY a.created_at DESC
            """
        ).fetchall()
    return [_row_to_dict(row) for row in rows]


def create_action(payload):
    init_auto_reup_db()
    now = _now()
    data = {
        "id": _new_id(),
        "name": payload.get("name", "").strip(),
        "target_page_id": payload.get("target_page_id") or None,
        "platform": (payload.get("platform") or "facebook").strip(),
        "source_url": payload.get("source_url", "").strip(),
        "template_id": payload.get("template_id") or "",
        "translate_caption": 1 if payload.get("translate_caption", True) else 0,
        "apply_frame": 1 if payload.get("apply_frame") else 0,
        "content_cleaner_enabled": 1 if payload.get("content_cleaner_enabled", True) else 0,
        "enabled": 1 if payload.get("enabled", True) else 0,
        "daily_limit": int(payload.get("daily_limit") or 3),
        "active_from": payload.get("active_from") or "09:00",
        "active_to": payload.get("active_to") or "22:30",
        "min_gap_minutes": int(payload.get("min_gap_minutes") or 180),
        "scan_interval_minutes": int(payload.get("scan_interval_minutes") or 60),
        "progress_total": int(payload.get("progress_total") or 0),
        "progress_scanned": int(payload.get("progress_scanned") or 0),
        "progress_posted": int(payload.get("progress_posted") or 0),
        "progress_errors": int(payload.get("progress_errors") or 0),
        "last_scan_at": payload.get("last_scan_at") or None,
        "notes": payload.get("notes") or "",
        "created_at": now,
        "updated_at": now,
    }

    if not data["name"]:
        raise ValueError("Missing action name")
    if not data["source_url"]:
        raise ValueError("Missing source URL")

    with _connect() as conn:
        conn.execute(
            """
            INSERT INTO reup_actions (
                id, name, target_page_id, platform, source_url, template_id,
                translate_caption, apply_frame, content_cleaner_enabled, enabled,
                daily_limit, active_from, active_to, min_gap_minutes,
                scan_interval_minutes, progress_total, progress_scanned,
                progress_posted, progress_errors, last_scan_at, notes,
                created_at, updated_at
            ) VALUES (
                :id, :name, :target_page_id, :platform, :source_url, :template_id,
                :translate_caption, :apply_frame, :content_cleaner_enabled, :enabled,
                :daily_limit, :active_from, :active_to, :min_gap_minutes,
                :scan_interval_minutes, :progress_total, :progress_scanned,
                :progress_posted, :progress_errors, :last_scan_at, :notes,
                :created_at, :updated_at
            )
            """,
            data,
        )
        conn.commit()

    return get_action(data["id"])


def get_action(action_id):
    init_auto_reup_db()
    with _connect() as conn:
        row = conn.execute(
            """
            SELECT a.*, p.name AS target_page_name, p.page_id AS target_page_external_id
            FROM reup_actions a
            LEFT JOIN fanpages p ON p.id = a.target_page_id
            WHERE a.id = ?
            """,
            (action_id,),
        ).fetchone()
    if not row:
        raise ValueError("Action not found")
    return _row_to_dict(row)


def update_action(action_id, payload):
    init_auto_reup_db()
    allowed = {
        "name",
        "target_page_id",
        "platform",
        "source_url",
        "template_id",
        "translate_caption",
        "apply_frame",
        "content_cleaner_enabled",
        "enabled",
        "daily_limit",
        "active_from",
        "active_to",
        "min_gap_minutes",
        "scan_interval_minutes",
        "progress_total",
        "progress_scanned",
        "progress_posted",
        "progress_errors",
        "last_scan_at",
        "notes",
    }
    updates = {key: value for key, value in payload.items() if key in allowed}
    if not updates:
        return get_action(action_id)

    for boolean_key in ["translate_caption", "apply_frame", "content_cleaner_enabled", "enabled"]:
        if boolean_key in updates:
            updates[boolean_key] = 1 if updates[boolean_key] else 0

    for numeric_key in [
        "daily_limit",
        "min_gap_minutes",
        "scan_interval_minutes",
        "progress_total",
        "progress_scanned",
        "progress_posted",
        "progress_errors",
    ]:
        if numeric_key in updates and updates[numeric_key] is not None:
            updates[numeric_key] = int(updates[numeric_key])

    updates["updated_at"] = _now()
    assignments = ", ".join([f"{key} = :{key}" for key in updates])
    updates["id"] = action_id

    with _connect() as conn:
        conn.execute(f"UPDATE reup_actions SET {assignments} WHERE id = :id", updates)
        conn.commit()

    return get_action(action_id)


def delete_action(action_id):
    init_auto_reup_db()
    with _connect() as conn:
        deleted = conn.execute("DELETE FROM reup_actions WHERE id = ?", (action_id,)).rowcount
        conn.commit()

    if not deleted:
        raise ValueError("Action not found")
    return {"id": action_id}


def list_jobs(status=None, limit=100):
    init_auto_reup_db()
    safe_limit = max(1, min(500, int(limit or 100)))

    with _connect() as conn:
        if status:
            rows = conn.execute(
                """
                SELECT j.*, s.name AS source_name, p.name AS target_page_name
                FROM reup_jobs j
                LEFT JOIN reup_sources s ON s.id = j.source_id
                LEFT JOIN fanpages p ON p.id = j.target_page_id
                WHERE j.status = ?
                ORDER BY j.created_at DESC
                LIMIT ?
                """,
                (status, safe_limit),
            ).fetchall()
        else:
            rows = conn.execute(
                """
                SELECT j.*, s.name AS source_name, p.name AS target_page_name
                FROM reup_jobs j
                LEFT JOIN reup_sources s ON s.id = j.source_id
                LEFT JOIN fanpages p ON p.id = j.target_page_id
                ORDER BY j.created_at DESC
                LIMIT ?
                """,
                (safe_limit,),
            ).fetchall()

    return [_row_to_dict(row) for row in rows]


def create_job(payload):
    init_auto_reup_db()
    cleaned = clean_post_content(payload.get("raw_content", ""))
    now = _now()
    data = {
        "id": _new_id(),
        "source_id": payload.get("source_id") or None,
        "target_page_id": payload.get("target_page_id") or None,
        "source_post_id": payload.get("source_post_id") or "",
        "source_video_url": payload.get("source_video_url") or "",
        "raw_content": cleaned["raw_content"],
        "clean_content": payload.get("clean_content") or cleaned["clean_content"],
        "removed_links": json.dumps(cleaned["removed_links"], ensure_ascii=False),
        "removed_lines": json.dumps(cleaned["removed_lines"], ensure_ascii=False),
        "status": payload.get("status") or "queued",
        "scheduled_at": payload.get("scheduled_at") or None,
        "posted_at": payload.get("posted_at") or None,
        "error": payload.get("error") or "",
        "created_at": now,
        "updated_at": now,
    }

    with _connect() as conn:
        conn.execute(
            """
            INSERT INTO reup_jobs (
                id, source_id, target_page_id, source_post_id, source_video_url,
                raw_content, clean_content, removed_links, removed_lines, status,
                scheduled_at, posted_at, error, created_at, updated_at
            ) VALUES (
                :id, :source_id, :target_page_id, :source_post_id, :source_video_url,
                :raw_content, :clean_content, :removed_links, :removed_lines, :status,
                :scheduled_at, :posted_at, :error, :created_at, :updated_at
            )
            """,
            data,
        )
        conn.commit()

    return get_job(data["id"])


def get_job(job_id):
    with _connect() as conn:
        row = conn.execute(
            """
            SELECT j.*, s.name AS source_name, p.name AS target_page_name
            FROM reup_jobs j
            LEFT JOIN reup_sources s ON s.id = j.source_id
            LEFT JOIN fanpages p ON p.id = j.target_page_id
            WHERE j.id = ?
            """,
            (job_id,),
        ).fetchone()
    if not row:
        raise ValueError("Job not found")
    return _row_to_dict(row)


def update_job(job_id, payload):
    init_auto_reup_db()
    allowed = {
        "source_id",
        "target_page_id",
        "source_post_id",
        "source_video_url",
        "raw_content",
        "clean_content",
        "status",
        "scheduled_at",
        "posted_at",
        "error",
    }
    updates = {key: value for key, value in payload.items() if key in allowed}
    if not updates:
        return get_job(job_id)

    if "raw_content" in updates and "clean_content" not in updates:
        cleaned = clean_post_content(updates["raw_content"])
        updates["clean_content"] = cleaned["clean_content"]
        updates["removed_links"] = json.dumps(cleaned["removed_links"], ensure_ascii=False)
        updates["removed_lines"] = json.dumps(cleaned["removed_lines"], ensure_ascii=False)

    updates["updated_at"] = _now()
    assignments = ", ".join([f"{key} = :{key}" for key in updates])
    updates["id"] = job_id

    with _connect() as conn:
        conn.execute(f"UPDATE reup_jobs SET {assignments} WHERE id = :id", updates)
        conn.commit()

    return get_job(job_id)


def delete_job(job_id):
    init_auto_reup_db()
    with _connect() as conn:
        deleted = conn.execute("DELETE FROM reup_jobs WHERE id = ?", (job_id,)).rowcount
        conn.commit()

    if not deleted:
        raise ValueError("Job not found")
    return {"id": job_id}
