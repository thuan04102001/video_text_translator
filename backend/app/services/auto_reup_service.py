import json
import hashlib
import os
import random
import re
import shutil
import sqlite3
import threading
import time
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlparse
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import requests
from cryptography.fernet import Fernet, InvalidToken
from dotenv import load_dotenv

from app.services.frame_template_service import load_frame_template


BASE_DIR = Path(__file__).resolve().parents[2]
load_dotenv(BASE_DIR.parent / ".env")
DATA_DIR = BASE_DIR / "data"
DB_PATH = DATA_DIR / "auto_reup.sqlite3"
TOKEN_KEY_PATH = DATA_DIR / "meta_token.key"
GRAPH_API_VERSION = os.getenv("META_GRAPH_VERSION", "v20.0").strip() or "v20.0"
META_APP_ID = os.getenv("META_APP_ID", "").strip()
META_APP_SECRET = os.getenv("META_APP_SECRET", "").strip()
TOKEN_MONITOR_INTERVAL_SECONDS = max(
    30,
    int(os.getenv("META_TOKEN_MONITOR_INTERVAL_SECONDS", "60") or 60),
)
def _load_auto_reup_timezone():
    timezone_name = os.getenv("AUTO_REUP_TIMEZONE", "Asia/Bangkok").strip() or "Asia/Bangkok"
    try:
        return ZoneInfo(timezone_name)
    except ZoneInfoNotFoundError:
        if timezone_name == "Asia/Bangkok":
            return timezone(timedelta(hours=7), "Asia/Bangkok")
        return timezone.utc


AUTO_REUP_TIMEZONE = _load_auto_reup_timezone()
AUTO_REUP_RUNTIME_INTERVAL_SECONDS = max(
    2,
    int(os.getenv("AUTO_REUP_RUNTIME_INTERVAL_SECONDS", "5") or 5),
)
AUTO_REUP_PREPARE_WORKERS = max(
    1,
    min(4, int(os.getenv("AUTO_REUP_PREPARE_WORKERS", "1") or 1)),
)
AUTO_REUP_JOB_DIR = DATA_DIR / "auto_reup_jobs"

_TOKEN_SYNC_LOCK = threading.RLock()
_TOKEN_SYNC_REQUEST_LOCK = threading.RLock()
_TOKEN_SYNCS_RUNNING = set()
_TOKEN_MONITOR_STOP = threading.Event()
_TOKEN_MONITOR_THREAD = None
_ACTION_MONITOR_STOP = threading.Event()
_ACTION_MONITOR_THREAD = None
_ACTION_SCAN_LOCK = threading.RLock()
_ACTION_SCANS_RUNNING = set()
_FACEBOOK_SCAN_LOCK = threading.Lock()
_RUNTIME_STOP = threading.Event()
_RUNTIME_THREAD = None
_PREPARE_LOCK = threading.RLock()
_PREPARE_JOBS_RUNNING = set()
_PUBLISH_LOCK = threading.Lock()
_SCHEDULE_RANDOM = random.SystemRandom()
SCHEDULE_MODES = {"random_interval", "manual_times", "smart_daily"}
SMART_PROFILES = {"vn", "us"}
VN_GOLDEN_WINDOWS = [(7 * 60, 9 * 60), (11 * 60, 13 * 60), (16 * 60 + 30, 18 * 60 + 30), (19 * 60 + 30, 22 * 60 + 30)]
US_GOLDEN_WINDOWS = [(6 * 60, 10 * 60), (10 * 60, 13 * 60), (20 * 60, 23 * 60)]
SOURCE_SCAN_INITIAL_LIMIT = max(20, int(os.getenv("AUTO_REUP_SOURCE_INITIAL_LIMIT", "100") or 100))
SOURCE_SCAN_INCREMENTAL_LIMIT = max(10, int(os.getenv("AUTO_REUP_SOURCE_INCREMENTAL_LIMIT", "60") or 60))
SOURCE_SCAN_STOP_KNOWN = max(3, int(os.getenv("AUTO_REUP_SOURCE_STOP_KNOWN", "10") or 10))
ACTION_QUEUE_BUFFER_DAYS = max(1, int(os.getenv("AUTO_REUP_QUEUE_BUFFER_DAYS", "2") or 2))
PAGE_INSIGHTS_REFRESH_MINUTES = max(
    15,
    int(os.getenv("AUTO_REUP_PAGE_INSIGHTS_REFRESH_MINUTES", "60") or 60),
)

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


def _parse_iso(value):
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None


def _utc_from_timestamp(value):
    try:
        timestamp = int(value or 0)
    except (TypeError, ValueError):
        timestamp = 0
    if timestamp <= 0:
        return None
    return datetime.fromtimestamp(timestamp, timezone.utc).isoformat(timespec="seconds")


def _token_cipher():
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    if not TOKEN_KEY_PATH.exists():
        TOKEN_KEY_PATH.write_bytes(Fernet.generate_key())
    return Fernet(TOKEN_KEY_PATH.read_bytes().strip())


def _encrypt_secret(value):
    secret = str(value or "").strip()
    if not secret:
        return ""
    return _token_cipher().encrypt(secret.encode("utf-8")).decode("ascii")


def _decrypt_secret(value):
    encrypted = str(value or "").strip()
    if not encrypted:
        return ""
    try:
        return _token_cipher().decrypt(encrypted.encode("ascii")).decode("utf-8")
    except (InvalidToken, ValueError) as error:
        raise ValueError("Stored Meta token cannot be decrypted on this machine") from error


def _token_fingerprint(value):
    token = str(value or "").strip()
    if not token:
        return ""
    digest = hashlib.sha256(token.encode("utf-8")).hexdigest()[:12]
    suffix = token[-6:] if len(token) >= 6 else token
    return f"{digest}:{suffix}"


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
    for key in [
        "removed_links",
        "removed_lines",
        "manual_times",
        "meta_sources",
        "meta_business_ids",
        "meta_business_names",
    ]:
        if key in data:
            data[key] = _decode_json(data[key], [])
    if "meta_tasks" in data:
        data["meta_tasks"] = _decode_json(data["meta_tasks"], [])
    if "page_access_token" in data:
        data["has_page_access_token"] = bool(data.get("page_access_token"))
        data.pop("page_access_token", None)
    for key in [
        "is_enabled",
        "enabled",
        "translate_caption",
        "apply_frame",
        "content_cleaner_enabled",
        "creative_remove_source_audio",
        "creative_randomize_variant",
        "creative_smart_audio",
    ]:
        if key in data:
            data[key] = bool(data[key])
    return data


def _meta_token_row_to_dict(row):
    data = dict(row)
    data.pop("encrypted_token", None)
    data["auto_sync"] = bool(data.get("auto_sync"))
    data["has_token"] = bool(data.get("token_fingerprint"))
    data["business_ids"] = _decode_json(data.get("business_ids"), [])
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
                action_id TEXT,
                source_id TEXT,
                target_page_id TEXT,
                source_post_id TEXT,
                source_video_url TEXT,
                raw_content TEXT,
                clean_content TEXT,
                removed_links TEXT,
                removed_lines TEXT,
                status TEXT NOT NULL DEFAULT 'queued',
                stage TEXT NOT NULL DEFAULT 'queued',
                progress INTEGER NOT NULL DEFAULT 0,
                source_local_path TEXT,
                output_path TEXT,
                publish_id TEXT,
                attempts INTEGER NOT NULL DEFAULT 0,
                scheduled_at TEXT,
                posted_at TEXT,
                error TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                FOREIGN KEY(action_id) REFERENCES reup_actions(id),
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
                creative_remove_source_audio INTEGER NOT NULL DEFAULT 1,
                creative_randomize_variant INTEGER NOT NULL DEFAULT 1,
                creative_smart_audio INTEGER NOT NULL DEFAULT 1,
                creative_audio_volume REAL NOT NULL DEFAULT 1.0,
                creative_custom_audio_path TEXT,
                content_cleaner_enabled INTEGER NOT NULL DEFAULT 1,
                enabled INTEGER NOT NULL DEFAULT 1,
                daily_limit INTEGER NOT NULL DEFAULT 3,
                active_from TEXT NOT NULL DEFAULT '09:00',
                active_to TEXT NOT NULL DEFAULT '22:30',
                min_gap_minutes INTEGER NOT NULL DEFAULT 180,
                max_gap_minutes INTEGER NOT NULL DEFAULT 250,
                schedule_mode TEXT NOT NULL DEFAULT 'random_interval',
                manual_times TEXT,
                smart_profile TEXT NOT NULL DEFAULT 'vn',
                jitter_minutes INTEGER NOT NULL DEFAULT 15,
                scan_interval_minutes INTEGER NOT NULL DEFAULT 60,
                progress_total INTEGER NOT NULL DEFAULT 0,
                progress_scanned INTEGER NOT NULL DEFAULT 0,
                progress_posted INTEGER NOT NULL DEFAULT 0,
                progress_errors INTEGER NOT NULL DEFAULT 0,
                last_scan_at TEXT,
                scan_status TEXT NOT NULL DEFAULT 'idle',
                last_scan_error TEXT,
                notes TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                FOREIGN KEY(target_page_id) REFERENCES fanpages(id)
            );

            CREATE TABLE IF NOT EXISTS reup_action_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                action_id TEXT NOT NULL,
                job_id TEXT,
                level TEXT NOT NULL DEFAULT 'info',
                event_type TEXT NOT NULL,
                message TEXT NOT NULL,
                payload TEXT,
                created_at TEXT NOT NULL,
                FOREIGN KEY(action_id) REFERENCES reup_actions(id) ON DELETE CASCADE,
                FOREIGN KEY(job_id) REFERENCES reup_jobs(id) ON DELETE SET NULL
            );

            CREATE TABLE IF NOT EXISTS source_video_inventory (
                id TEXT PRIMARY KEY,
                source_key TEXT NOT NULL,
                platform TEXT NOT NULL,
                source_url TEXT NOT NULL,
                source_post_id TEXT NOT NULL,
                source_video_url TEXT NOT NULL,
                raw_content TEXT,
                clean_content TEXT,
                removed_links TEXT,
                removed_lines TEXT,
                source_published_at TEXT,
                first_seen_at TEXT NOT NULL,
                last_seen_at TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                UNIQUE(source_key, source_post_id)
            );

            CREATE TABLE IF NOT EXISTS posted_source_history (
                id TEXT PRIMARY KEY,
                target_page_id TEXT NOT NULL,
                source_key TEXT NOT NULL,
                platform TEXT NOT NULL,
                source_post_id TEXT NOT NULL,
                source_video_url TEXT NOT NULL,
                source_hash TEXT NOT NULL,
                action_id TEXT,
                job_id TEXT,
                publish_id TEXT,
                posted_at TEXT NOT NULL,
                created_at TEXT NOT NULL,
                UNIQUE(target_page_id, source_hash)
            );

            CREATE TABLE IF NOT EXISTS page_insight_snapshots (
                id TEXT PRIMARY KEY,
                fanpage_id TEXT NOT NULL,
                period TEXT NOT NULL,
                views INTEGER,
                engagements INTEGER,
                followers INTEGER,
                estimated_earnings REAL,
                metrics_json TEXT,
                fetched_at TEXT NOT NULL,
                error TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                UNIQUE(fanpage_id, period)
            );

            CREATE TABLE IF NOT EXISTS page_insight_history (
                id TEXT PRIMARY KEY,
                fanpage_id TEXT NOT NULL,
                views INTEGER,
                engagements INTEGER,
                followers INTEGER,
                estimated_earnings REAL,
                metrics_json TEXT,
                fetched_at TEXT NOT NULL,
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS meta_user_tokens (
                id TEXT PRIMARY KEY,
                label TEXT NOT NULL,
                credential_type TEXT NOT NULL DEFAULT 'user_oauth',
                business_ids TEXT,
                encrypted_token TEXT NOT NULL,
                token_fingerprint TEXT NOT NULL,
                graph_version TEXT NOT NULL DEFAULT '',
                meta_user_id TEXT,
                meta_user_name TEXT,
                meta_app_id TEXT,
                token_type TEXT,
                expires_at TEXT,
                data_access_expires_at TEXT,
                status TEXT NOT NULL DEFAULT 'unknown',
                auto_sync INTEGER NOT NULL DEFAULT 1,
                check_interval_minutes INTEGER NOT NULL DEFAULT 360,
                last_checked_at TEXT,
                last_sync_at TEXT,
                last_error TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS meta_token_page_links (
                token_id TEXT NOT NULL,
                fanpage_id TEXT NOT NULL,
                encrypted_page_token TEXT,
                meta_sources TEXT,
                meta_business_ids TEXT,
                meta_business_names TEXT,
                last_seen_at TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                PRIMARY KEY(token_id, fanpage_id),
                FOREIGN KEY(token_id) REFERENCES meta_user_tokens(id) ON DELETE CASCADE,
                FOREIGN KEY(fanpage_id) REFERENCES fanpages(id) ON DELETE CASCADE
            );
            """
        )
        _ensure_columns(
            conn,
            "reup_jobs",
            {
                "action_id": "TEXT",
                "stage": "TEXT NOT NULL DEFAULT 'queued'",
                "progress": "INTEGER NOT NULL DEFAULT 0",
                "source_local_path": "TEXT",
                "output_path": "TEXT",
                "publish_id": "TEXT",
                "attempts": "INTEGER NOT NULL DEFAULT 0",
            },
        )
        _ensure_columns(
            conn,
            "reup_actions",
            {
                "max_gap_minutes": "INTEGER NOT NULL DEFAULT 250",
                "schedule_mode": "TEXT NOT NULL DEFAULT 'random_interval'",
                "manual_times": "TEXT",
                "smart_profile": "TEXT NOT NULL DEFAULT 'vn'",
                "jitter_minutes": "INTEGER NOT NULL DEFAULT 15",
                "scan_status": "TEXT NOT NULL DEFAULT 'idle'",
                "last_scan_error": "TEXT",
                "creative_remove_source_audio": "INTEGER NOT NULL DEFAULT 1",
                "creative_randomize_variant": "INTEGER NOT NULL DEFAULT 1",
                "creative_smart_audio": "INTEGER NOT NULL DEFAULT 1",
                "creative_audio_volume": "REAL NOT NULL DEFAULT 1.0",
                "creative_custom_audio_path": "TEXT",
            },
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
                "meta_sources": "TEXT",
                "meta_business_ids": "TEXT",
                "meta_business_names": "TEXT",
                "meta_last_seen_at": "TEXT",
                "page_token_status": "TEXT NOT NULL DEFAULT 'unknown'",
                "page_token_last_checked_at": "TEXT",
                "page_token_last_error": "TEXT",
                "credential_id": "TEXT",
            },
        )
        _ensure_columns(
            conn,
            "meta_user_tokens",
            {
                "credential_type": "TEXT NOT NULL DEFAULT 'user_oauth'",
                "business_ids": "TEXT",
            },
        )
        _ensure_columns(
            conn,
            "meta_token_page_links",
            {
                "page_token_status": "TEXT NOT NULL DEFAULT 'unknown'",
                "page_token_last_checked_at": "TEXT",
                "page_token_last_error": "TEXT",
            },
        )
        _ensure_columns(
            conn,
            "reup_actions",
            {
                "max_gap_minutes": "INTEGER NOT NULL DEFAULT 250",
                "schedule_mode": "TEXT NOT NULL DEFAULT 'random_interval'",
                "manual_times": "TEXT",
                "smart_profile": "TEXT NOT NULL DEFAULT 'vn'",
                "jitter_minutes": "INTEGER NOT NULL DEFAULT 15",
            },
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_meta_tokens_auto_sync "
            "ON meta_user_tokens(auto_sync, status, last_checked_at)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_meta_token_pages_page "
            "ON meta_token_page_links(fanpage_id)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_reup_jobs_action "
            "ON reup_jobs(action_id, source_post_id)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_reup_jobs_runtime "
            "ON reup_jobs(status, scheduled_at, created_at)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_reup_action_events "
            "ON reup_action_events(action_id, created_at DESC)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_source_inventory_key_seen "
            "ON source_video_inventory(source_key, first_seen_at DESC)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_posted_source_target "
            "ON posted_source_history(target_page_id, source_hash)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_page_insights_page "
            "ON page_insight_snapshots(fanpage_id, period, fetched_at)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_page_insight_history_page "
            "ON page_insight_history(fanpage_id, fetched_at)"
        )
        conn.execute(
            "UPDATE reup_actions SET scan_status = 'idle' "
            "WHERE scan_status = 'scanning'"
        )
        conn.execute(
            """
            UPDATE reup_jobs
            SET status = CASE WHEN COALESCE(output_path, '') != '' THEN 'ready' ELSE 'queued' END,
                stage = CASE WHEN COALESCE(output_path, '') != '' THEN 'ready' ELSE 'queued' END,
                progress = CASE WHEN COALESCE(output_path, '') != '' THEN 95 ELSE 0 END,
                error = CASE
                    WHEN COALESCE(error, '') = '' THEN 'Recovered after application restart'
                    ELSE error
                END,
                updated_at = ?
            WHERE status IN ('processing', 'publishing')
            """,
            (_now(),),
        )
        conn.execute(
            """
            INSERT INTO reup_action_events (
                action_id, job_id, level, event_type, message, payload, created_at
            )
            SELECT a.id, NULL, 'info', 'runtime_monitoring',
                   'Runtime detail da san sang theo doi action.',
                   '', ?
            FROM reup_actions a
            WHERE NOT EXISTS (
                SELECT 1
                FROM reup_action_events event
                WHERE event.action_id = a.id
            )
            """,
            (_now(),),
        )
        conn.execute(
            """
            UPDATE fanpages
            SET credential_id = (
                SELECT link.token_id
                FROM meta_token_page_links link
                WHERE link.fanpage_id = fanpages.id
                ORDER BY link.created_at ASC
                LIMIT 1
            )
            WHERE COALESCE(credential_id, '') = ''
              AND (
                SELECT COUNT(*)
                FROM meta_token_page_links link
                WHERE link.fanpage_id = fanpages.id
              ) = 1
            """
        )
        posted_rows = conn.execute(
            """
            SELECT j.id AS job_id, j.action_id, j.target_page_id,
                   j.source_post_id, j.source_video_url, j.publish_id,
                   j.posted_at, a.platform, a.source_url
            FROM reup_jobs j
            LEFT JOIN reup_actions a ON a.id = j.action_id
            WHERE j.status = 'posted'
              AND COALESCE(j.target_page_id, '') != ''
              AND COALESCE(j.source_post_id, '') != ''
            """
        ).fetchall()
        for row in posted_rows:
            platform = (row["platform"] or "facebook").strip().lower()
            source_url = _normalize_source_url(row["source_url"])
            posted_at = row["posted_at"] or _now()
            conn.execute(
                """
                INSERT OR IGNORE INTO posted_source_history (
                    id, target_page_id, source_key, platform, source_post_id,
                    source_video_url, source_hash, action_id, job_id, publish_id,
                    posted_at, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    _new_id(),
                    row["target_page_id"],
                    f"{platform}:{source_url.casefold()}",
                    platform,
                    row["source_post_id"],
                    row["source_video_url"] or "",
                    _source_hash(row["source_post_id"], row["source_video_url"]),
                    row["action_id"],
                    row["job_id"],
                    row["publish_id"] or "",
                    posted_at,
                    posted_at,
                ),
            )
        conn.commit()


def _record_action_event(
    action_id,
    event_type,
    message,
    *,
    job_id=None,
    level="info",
    payload=None,
):
    if not action_id:
        return
    serialized_payload = ""
    if payload:
        serialized_payload = json.dumps(payload, ensure_ascii=False)
    with _connect() as conn:
        conn.execute(
            """
            INSERT INTO reup_action_events (
                action_id, job_id, level, event_type, message, payload, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                action_id,
                job_id or None,
                level,
                event_type,
                str(message or event_type),
                serialized_payload,
                _now(),
            ),
        )
        conn.execute(
            """
            DELETE FROM reup_action_events
            WHERE action_id = ?
              AND id NOT IN (
                  SELECT id
                  FROM reup_action_events
                  WHERE action_id = ?
                  ORDER BY id DESC
                  LIMIT 500
              )
            """,
            (action_id, action_id),
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
            """
            SELECT COUNT(*)
            FROM reup_jobs
            WHERE status IN ('queued', 'processing', 'ready', 'publishing')
            """
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
            WHERE access_status IN ('connected', 'degraded')
              AND COALESCE(page_access_token, '') != ''
            """
        ).fetchone()[0]
        degraded_pages = conn.execute(
            """
            SELECT COUNT(*)
            FROM fanpages
            WHERE access_status = 'degraded'
              AND COALESCE(page_access_token, '') != ''
            """
        ).fetchone()[0]
        stale_pages = conn.execute(
            "SELECT COUNT(*) FROM fanpages WHERE access_status = 'stale'"
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
        "connected_pages": connected_pages,
        "degraded_pages": degraded_pages,
        "stale_pages": stale_pages,
        "publish_status": "meta_connected" if connected_pages else "waiting_for_meta_api",
    }


def list_pages():
    init_auto_reup_db()
    with _connect() as conn:
        _cleanup_orphan_meta_pages(conn)
        rows = conn.execute(
            "SELECT * FROM fanpages ORDER BY created_at DESC"
        ).fetchall()
        owner_rows = conn.execute(
            """
            SELECT link.fanpage_id,
                   token.id AS token_id,
                   token.label,
                   token.credential_type,
                   token.meta_user_id,
                   token.meta_user_name,
                   token.status,
                   token.auto_sync,
                   CASE WHEN page.credential_id = token.id THEN 1 ELSE 0 END AS is_primary,
                   link.page_token_status,
                   link.page_token_last_checked_at,
                   link.page_token_last_error
            FROM meta_token_page_links link
            JOIN meta_user_tokens token ON token.id = link.token_id
            JOIN fanpages page ON page.id = link.fanpage_id
            ORDER BY is_primary DESC, token.label COLLATE NOCASE, token.created_at
            """
        ).fetchall()

    owners_by_page = {}
    for owner in owner_rows:
        owners_by_page.setdefault(owner["fanpage_id"], []).append({
            "token_id": owner["token_id"],
            "label": owner["label"],
            "credential_type": owner["credential_type"] or "user_oauth",
            "meta_user_id": owner["meta_user_id"] or "",
            "meta_user_name": owner["meta_user_name"] or "",
            "status": owner["status"] or "unknown",
            "auto_sync": bool(owner["auto_sync"]),
            "is_primary": bool(owner["is_primary"]),
            "page_token_status": owner["page_token_status"] or "unknown",
            "page_token_last_checked_at": owner["page_token_last_checked_at"],
            "page_token_last_error": owner["page_token_last_error"] or "",
        })

    pages = []
    for row in rows:
        page = _row_to_dict(row)
        page["meta_token_owners"] = owners_by_page.get(page["id"], [])
        pages.append(page)
    return pages


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
        if isinstance(meta_error, dict):
            message = meta_error.get("message") or response.text
            code = meta_error.get("code")
            subcode = meta_error.get("error_subcode")
            if code is not None:
                message = f"{message} (code {code}"
                if subcode is not None:
                    message += f", subcode {subcode}"
                message += ")"
        else:
            message = response.text
        raise ValueError(f"Meta API error: {message}")

    return payload


def _graph_get_next(next_url):
    try:
        response = requests.get(next_url, timeout=25)
        payload = response.json()
    except requests.RequestException as error:
        raise ValueError(f"Meta API paging failed: {error}") from error
    except ValueError as error:
        raise ValueError("Meta API returned invalid JSON while paging") from error

    if response.status_code >= 400 or "error" in payload:
        meta_error = payload.get("error") if isinstance(payload, dict) else None
        if isinstance(meta_error, dict):
            message = meta_error.get("message") or response.text
            code = meta_error.get("code")
            subcode = meta_error.get("error_subcode")
            if code is not None:
                message = f"{message} (code {code}"
                if subcode is not None:
                    message += f", subcode {subcode}"
                message += ")"
        else:
            message = response.text
        raise ValueError(f"Meta API error: {message}")
    return payload


def _graph_collect(path, access_token, params=None, graph_version=None, max_pages=100):
    payload = _graph_get(
        path,
        access_token,
        params,
        graph_version=graph_version,
    )
    items = []
    pages_read = 0

    while pages_read < max_pages:
        data = payload.get("data", [])
        if isinstance(data, list):
            items.extend(data)
        pages_read += 1

        next_url = payload.get("paging", {}).get("next")
        if not next_url:
            break
        payload = _graph_get_next(next_url)

    if pages_read >= max_pages and payload.get("paging", {}).get("next"):
        raise ValueError(f"Meta API paging exceeded safety limit for {path}")
    return items


def _metric_number(payload):
    values = payload.get("values") if isinstance(payload, dict) else None
    if not isinstance(values, list):
        return None
    total = 0.0
    found = False
    for item in values:
        value = item.get("value") if isinstance(item, dict) else None
        if isinstance(value, dict):
            numeric = sum(
                float(child)
                for child in value.values()
                if isinstance(child, (int, float))
            )
        elif isinstance(value, (int, float)):
            numeric = float(value)
        else:
            continue
        total += numeric
        found = True
    if not found:
        return None
    return int(total) if total.is_integer() else total


def _fetch_first_metric_value(page_id, access_token, metric_names, since, until, graph_version=None):
    for metric in metric_names:
        try:
            payload = _graph_get(
                f"{page_id}/insights",
                access_token,
                {
                    "metric": metric,
                    "period": "day",
                    "since": since,
                    "until": until,
                },
                graph_version=graph_version,
            )
        except ValueError:
            continue
        data = payload.get("data") or []
        if not data:
            continue
        value = _metric_number(data[0])
        if value is not None:
            return value, metric
    return None, ""


def _parse_graph_datetime(value):
    text = str(value or "").strip()
    if re.search(r"[+-]\d{4}$", text):
        text = f"{text[:-5]}{text[-5:-2]}:{text[-2:]}"
    return _parse_iso(text)


def _graph_item_in_window(item, since=None, until=None):
    if since is None and until is None:
        return True
    created_at = _parse_graph_datetime(item.get("created_time") if isinstance(item, dict) else None)
    if not created_at:
        return False
    timestamp = int(created_at.astimezone(timezone.utc).timestamp())
    if since is not None and timestamp < int(since):
        return False
    if until is not None and timestamp > int(until):
        return False
    return True


def _fetch_page_video_rollup(page_id, access_token, since=None, until=None, graph_version=None):
    params = {
        "fields": "id,created_time,views",
        "limit": 100,
    }
    if since is not None:
        params["since"] = since
    if until is not None:
        params["until"] = until
    videos = _graph_collect(
        f"{page_id}/videos",
        access_token,
        params,
        graph_version=graph_version,
        max_pages=20,
    )
    total_views = 0
    total_items = 0
    for video in videos:
        if not isinstance(video, dict) or not _graph_item_in_window(video, since, until):
            continue
        total_items += 1
        try:
            total_views += int(video.get("views") or 0)
        except (TypeError, ValueError):
            continue
    return {"views": total_views, "items": total_items}


def _summary_count(payload):
    if not isinstance(payload, dict):
        return 0
    summary = payload.get("summary")
    if not isinstance(summary, dict):
        return 0
    try:
        return int(summary.get("total_count") or 0)
    except (TypeError, ValueError):
        return 0


def _fetch_page_post_engagement_rollup(page_id, access_token, since=None, until=None, graph_version=None):
    params = {
        "fields": "id,created_time,shares,comments.summary(true),reactions.summary(true)",
        "limit": 100,
    }
    if since is not None:
        params["since"] = since
    if until is not None:
        params["until"] = until
    posts = _graph_collect(
        f"{page_id}/published_posts",
        access_token,
        params,
        graph_version=graph_version,
        max_pages=20,
    )
    total_engagements = 0
    total_items = 0
    for post in posts:
        if not isinstance(post, dict) or not _graph_item_in_window(post, since, until):
            continue
        total_items += 1
        shares = post.get("shares") if isinstance(post.get("shares"), dict) else {}
        try:
            share_count = int(shares.get("count") or 0)
        except (TypeError, ValueError):
            share_count = 0
        total_engagements += (
            share_count
            + _summary_count(post.get("comments"))
            + _summary_count(post.get("reactions"))
        )
    return {"engagements": total_engagements, "items": total_items}


def _fetch_page_total_followers(page_id, access_token, graph_version=None):
    payload = _graph_get(
        page_id,
        access_token,
        {"fields": "followers_count,fan_count"},
        graph_version=graph_version,
    )
    followers = payload.get("followers_count")
    metric = "followers_count"
    if followers is None:
        followers = payload.get("fan_count")
        metric = "fan_count"
    return followers, metric if followers is not None else ""


def _metric_trend(current, previous):
    if current is None or previous is None:
        return None
    try:
        current_value = float(current)
        previous_value = float(previous)
    except (TypeError, ValueError):
        return None
    delta = current_value - previous_value
    if previous_value == 0:
        percent = None if delta else 0
    else:
        percent = round((delta / previous_value) * 100, 2)
    direction = "flat"
    if delta > 0:
        direction = "up"
    elif delta < 0:
        direction = "down"
    return {
        "delta": int(delta) if float(delta).is_integer() else delta,
        "percent": percent,
        "direction": direction,
        "previous": int(previous_value) if float(previous_value).is_integer() else previous_value,
    }


def _load_insight_trends(conn, fanpage_id, fetched_at):
    current_at = _parse_iso(fetched_at)
    if not current_at:
        return {}
    if current_at.tzinfo is None:
        current_at = current_at.replace(tzinfo=timezone.utc)
    local_now = current_at.astimezone(AUTO_REUP_TIMEZONE)
    today_start = datetime.combine(local_now.date(), datetime.min.time(), tzinfo=AUTO_REUP_TIMEZONE)
    yesterday_start = today_start - timedelta(days=1)
    yesterday_end = today_start
    window_start = yesterday_start.astimezone(timezone.utc).isoformat(timespec="seconds")
    window_end = yesterday_end.astimezone(timezone.utc).isoformat(timespec="seconds")
    previous = conn.execute(
        """
        SELECT views, engagements, followers, estimated_earnings, fetched_at
        FROM page_insight_history
        WHERE fanpage_id = ?
          AND fetched_at >= ?
          AND fetched_at < ?
        ORDER BY fetched_at DESC
        LIMIT 1
        """,
        (fanpage_id, window_start, window_end),
    ).fetchone()
    if not previous:
        return {}
    return {
        "baseline_fetched_at": previous["fetched_at"],
        "baseline_period": "yesterday_vn",
        "baseline_local_date": yesterday_start.date().isoformat(),
        "views": previous["views"],
        "engagements": previous["engagements"],
        "followers": previous["followers"],
        "estimated_earnings": previous["estimated_earnings"],
    }


def get_page_insight_snapshots(fanpage_id):
    with _connect() as conn:
        rows = conn.execute(
            """
            SELECT period, views, engagements, followers, estimated_earnings,
                   metrics_json, fetched_at, error
            FROM page_insight_snapshots
            WHERE fanpage_id = ?
            """,
            (fanpage_id,),
        ).fetchall()
        snapshots = {
            "total": {
                "views": None,
                "engagements": None,
                "followers": None,
                "estimated_earnings": None,
                "trend": {},
            },
        }
        for row in rows:
            if row["period"] != "total":
                continue
            try:
                metrics = json.loads(row["metrics_json"] or "{}")
            except Exception:
                metrics = {}
            trends = {}
            baseline = _load_insight_trends(conn, fanpage_id, row["fetched_at"])
            if baseline:
                trends = {
                    "baseline_fetched_at": baseline.get("baseline_fetched_at"),
                    "views": _metric_trend(row["views"], baseline.get("views")),
                    "engagements": _metric_trend(row["engagements"], baseline.get("engagements")),
                    "followers": _metric_trend(row["followers"], baseline.get("followers")),
                    "estimated_earnings": _metric_trend(
                        row["estimated_earnings"],
                        baseline.get("estimated_earnings"),
                    ),
                }
            snapshots["total"] = {
                "views": row["views"],
                "engagements": row["engagements"],
                "followers": row["followers"],
                "estimated_earnings": row["estimated_earnings"],
                "metrics": metrics if isinstance(metrics, dict) else {},
                "trend": trends,
                "fetched_at": row["fetched_at"],
                "error": row["error"] or "",
            }
    return snapshots


def refresh_page_insights(fanpage_id):
    credentials = _page_publish_credentials(fanpage_id)
    page = get_page(fanpage_id)
    page_id = str(page.get("page_id") or credentials["page_id"] or "").strip()
    if not page_id:
        raise ValueError("Fanpage does not have a Meta Page ID")

    now = _now()
    results = {}
    with _connect() as conn:
        metrics_used = {}
        error = ""
        try:
            video_rollup = _fetch_page_video_rollup(
                page_id,
                credentials["page_token"],
                graph_version=credentials["graph_version"],
            )
            engagement_rollup = _fetch_page_post_engagement_rollup(
                page_id,
                credentials["page_token"],
                graph_version=credentials["graph_version"],
            )
            views = video_rollup["views"]
            engagements = engagement_rollup["engagements"]
            metrics_used["views"] = "page_videos.views"
            metrics_used["engagements"] = "published_posts.summary"
            followers, followers_metric = _fetch_page_total_followers(
                page_id,
                credentials["page_token"],
                graph_version=credentials["graph_version"],
            )
            if followers is not None:
                metrics_used["followers"] = followers_metric
        except Exception as exc:
            views = engagements = followers = None
            error = str(exc)

        conn.execute(
            """
            INSERT INTO page_insight_snapshots (
                id, fanpage_id, period, views, engagements, followers,
                estimated_earnings, metrics_json, fetched_at, error,
                created_at, updated_at
            ) VALUES (?, ?, 'total', ?, ?, ?, NULL, ?, ?, ?, ?, ?)
            ON CONFLICT(fanpage_id, period) DO UPDATE SET
                views = excluded.views,
                engagements = excluded.engagements,
                followers = excluded.followers,
                estimated_earnings = excluded.estimated_earnings,
                metrics_json = excluded.metrics_json,
                fetched_at = excluded.fetched_at,
                error = excluded.error,
                updated_at = excluded.updated_at
            """,
            (
                _new_id(),
                fanpage_id,
                views,
                engagements,
                followers,
                json.dumps(metrics_used, ensure_ascii=False),
                now,
                error,
                now,
                now,
            ),
        )
        if not error and any(value is not None for value in (views, engagements, followers)):
            conn.execute(
                """
                INSERT INTO page_insight_history (
                    id, fanpage_id, views, engagements, followers,
                    estimated_earnings, metrics_json, fetched_at, created_at
                ) VALUES (?, ?, ?, ?, ?, NULL, ?, ?, ?)
                """,
                (
                    _new_id(),
                    fanpage_id,
                    views,
                    engagements,
                    followers,
                    json.dumps(metrics_used, ensure_ascii=False),
                    now,
                    now,
                ),
            )
        results["total"] = {
            "views": views,
            "engagements": engagements,
            "followers": followers,
            "estimated_earnings": None,
            "metrics": metrics_used,
            "fetched_at": now,
            "error": error,
        }
        conn.commit()
    return results


def _page_insights_due(fanpage_id, now=None):
    current = now or datetime.now(timezone.utc)
    with _connect() as conn:
        row = conn.execute(
            """
            SELECT MIN(fetched_at) AS oldest, COUNT(*) AS total
            FROM page_insight_snapshots
            WHERE fanpage_id = ?
              AND period = 'total'
            """,
            (fanpage_id,),
        ).fetchone()
    if not row or int(row["total"] or 0) < 1 or not row["oldest"]:
        return True
    fetched_at = _parse_iso(row["oldest"])
    if not fetched_at:
        return True
    return (current - fetched_at).total_seconds() >= PAGE_INSIGHTS_REFRESH_MINUTES * 60


def refresh_due_page_insights():
    pages = []
    with _connect() as conn:
        rows = conn.execute(
            """
            SELECT DISTINCT p.id
            FROM fanpages p
            JOIN reup_actions a ON a.target_page_id = p.id
            WHERE a.enabled = 1
              AND p.is_enabled = 1
              AND p.page_token_status = 'valid'
              AND COALESCE(p.page_access_token, '') != ''
            """
        ).fetchall()
        pages = [row["id"] for row in rows]
    refreshed = 0
    for fanpage_id in pages:
        if not _page_insights_due(fanpage_id):
            continue
        try:
            refresh_page_insights(fanpage_id)
            refreshed += 1
        except Exception:
            continue
    return {"refreshed": refreshed}


def _exchange_long_lived_user_token(access_token, graph_version=None):
    token = str(access_token or "").strip()
    if not token or not META_APP_ID or not META_APP_SECRET:
        return token, False

    version = (graph_version or GRAPH_API_VERSION).strip().strip("/")
    url = f"https://graph.facebook.com/{version}/oauth/access_token"
    params = {
        "grant_type": "fb_exchange_token",
        "client_id": META_APP_ID,
        "client_secret": META_APP_SECRET,
        "fb_exchange_token": token,
    }
    try:
        response = requests.get(url, params=params, timeout=25)
        payload = response.json()
    except requests.RequestException as error:
        raise ValueError(f"Meta long-lived token exchange failed: {error}") from error
    except ValueError as error:
        raise ValueError("Meta long-lived token exchange returned invalid JSON") from error

    if response.status_code >= 400 or payload.get("error"):
        meta_error = payload.get("error") if isinstance(payload, dict) else None
        message = meta_error.get("message") if isinstance(meta_error, dict) else response.text
        raise ValueError(f"Meta long-lived token exchange failed: {message}")
    exchanged = str(payload.get("access_token") or "").strip()
    return (exchanged or token), bool(exchanged)


def _inspect_meta_user_token(access_token, graph_version=None):
    token = str(access_token or "").strip()
    if not token:
        raise ValueError("Missing Meta user access token")

    profile = _graph_get(
        "me",
        token,
        {"fields": "id,name"},
        graph_version=graph_version,
    )
    debug = {}
    debug_warning = ""
    try:
        debug_payload = _graph_get(
            "debug_token",
            token,
            {"input_token": token},
            graph_version=graph_version,
        )
        debug = debug_payload.get("data") or {}
    except ValueError as error:
        debug_warning = str(error)

    if debug and not debug.get("is_valid", True):
        raise ValueError("Meta user access token is invalid or expired")

    expires_at = _utc_from_timestamp(debug.get("expires_at"))
    data_access_expires_at = _utc_from_timestamp(debug.get("data_access_expires_at"))
    token_type = debug.get("type") or "USER"
    return {
        "meta_user_id": str(profile.get("id") or debug.get("user_id") or ""),
        "meta_user_name": profile.get("name") or "",
        "meta_app_id": str(debug.get("app_id") or META_APP_ID or ""),
        "token_type": token_type,
        "expires_at": expires_at,
        "data_access_expires_at": data_access_expires_at,
        "status": "valid",
        "debug_warning": debug_warning,
    }


def list_meta_user_tokens():
    init_auto_reup_db()
    with _connect() as conn:
        rows = conn.execute(
            """
            SELECT token.*,
                   COUNT(link.fanpage_id) AS page_count,
                   SUM(CASE WHEN page.credential_id = token.id THEN 1 ELSE 0 END) AS assigned_page_count
            FROM meta_user_tokens token
            LEFT JOIN meta_token_page_links link ON link.token_id = token.id
            LEFT JOIN fanpages page ON page.id = link.fanpage_id
            GROUP BY token.id
            ORDER BY token.created_at ASC
            """
        ).fetchall()
    return [_meta_token_row_to_dict(row) for row in rows]


def get_meta_user_token(token_id, include_secret=False):
    init_auto_reup_db()
    with _connect() as conn:
        row = conn.execute(
            """
            SELECT token.*,
                   COUNT(link.fanpage_id) AS page_count,
                   SUM(CASE WHEN page.credential_id = token.id THEN 1 ELSE 0 END) AS assigned_page_count
            FROM meta_user_tokens token
            LEFT JOIN meta_token_page_links link ON link.token_id = token.id
            LEFT JOIN fanpages page ON page.id = link.fanpage_id
            WHERE token.id = ?
            GROUP BY token.id
            """,
            (token_id,),
        ).fetchone()
    if not row:
        raise ValueError("Meta user token account not found")
    if include_secret:
        data = dict(row)
        data["access_token"] = _decrypt_secret(data.get("encrypted_token"))
        data["business_ids"] = _decode_json(data.get("business_ids"), [])
        return data
    return _meta_token_row_to_dict(row)


def _token_due(row, now=None):
    if not row.get("auto_sync") or row.get("status") == "removed":
        return False
    checked_at = _parse_iso(row.get("last_checked_at"))
    if not checked_at:
        return True
    current = now or datetime.now(timezone.utc)
    interval_seconds = max(15, int(row.get("check_interval_minutes") or 360)) * 60
    return (current - checked_at).total_seconds() >= interval_seconds


def _normalize_credential_type(value):
    credential_type = str(value or "user_oauth").strip().lower()
    aliases = {
        "user": "user_oauth",
        "oauth": "user_oauth",
        "system": "system_user",
        "system-user": "system_user",
        "explorer": "test_token",
        "test": "test_token",
    }
    credential_type = aliases.get(credential_type, credential_type)
    if credential_type not in {"system_user", "user_oauth", "test_token"}:
        raise ValueError("Unsupported Meta credential type")
    return credential_type


def _normalize_business_ids(value):
    if isinstance(value, str):
        values = re.split(r"[\s,;]+", value)
    elif isinstance(value, (list, tuple, set)):
        values = value
    else:
        values = []
    result = []
    for item in values:
        business_id = str(item or "").strip()
        if business_id and business_id not in result:
            result.append(business_id)
    return result


def save_meta_user_token(payload, token_id=None, validate=True):
    init_auto_reup_db()
    access_token = str(payload.get("access_token") or "").strip()
    existing = get_meta_user_token(token_id, include_secret=True) if token_id else None
    if not access_token and existing:
        access_token = existing["access_token"]
    if not access_token:
        raise ValueError("Meta user access token is required")

    credential_type = _normalize_credential_type(
        payload.get("credential_type")
        or (existing or {}).get("credential_type")
        or "user_oauth"
    )
    business_ids = _normalize_business_ids(
        payload.get("business_ids")
        if "business_ids" in payload
        else (existing or {}).get("business_ids")
    )
    if credential_type == "system_user" and not business_ids:
        raise ValueError("System User credential requires at least one Business ID")

    graph_version = str(
        payload.get("graph_version")
        or (existing or {}).get("graph_version")
        or GRAPH_API_VERSION
    ).strip()
    exchange_requested = bool(payload.get("exchange_long_lived", True))
    exchanged = False
    exchange_warning = ""
    inspected = None
    if validate and (
        credential_type == "user_oauth"
        and exchange_requested
        and META_APP_ID
        and META_APP_SECRET
    ):
        try:
            access_token, exchanged = _exchange_long_lived_user_token(
                access_token,
                graph_version=graph_version,
            )
        except ValueError as error:
            exchange_warning = str(error)

    if validate:
        inspected = _inspect_meta_user_token(access_token, graph_version=graph_version)
    else:
        inspected = {
            "meta_user_id": (existing or {}).get("meta_user_id") or "",
            "meta_user_name": (existing or {}).get("meta_user_name") or "",
            "meta_app_id": (existing or {}).get("meta_app_id") or "",
            "token_type": (existing or {}).get("token_type") or "",
            "expires_at": (existing or {}).get("expires_at"),
            "data_access_expires_at": (existing or {}).get("data_access_expires_at"),
            "debug_warning": "Sync queued",
        }
    now = _now()
    data = {
        "id": token_id or _new_id(),
        "label": str(payload.get("label") or "").strip()
        or inspected["meta_user_name"]
        or (
            f"Meta account {inspected['meta_user_id']}"
            if inspected["meta_user_id"]
            else "Meta account"
        ),
        "credential_type": credential_type,
        "business_ids": json.dumps(business_ids, ensure_ascii=False),
        "encrypted_token": _encrypt_secret(access_token),
        "token_fingerprint": _token_fingerprint(access_token),
        "graph_version": graph_version,
        "meta_user_id": inspected["meta_user_id"],
        "meta_user_name": inspected["meta_user_name"],
        "meta_app_id": inspected["meta_app_id"],
        "token_type": inspected["token_type"],
        "expires_at": inspected["expires_at"],
        "data_access_expires_at": inspected["data_access_expires_at"],
        "status": "valid" if validate else "pending_sync",
        "auto_sync": 1 if payload.get("auto_sync", True) else 0,
        "check_interval_minutes": max(
            15,
            int(payload.get("check_interval_minutes") or 360),
        ),
        "last_checked_at": now,
        "last_sync_at": (existing or {}).get("last_sync_at"),
        "last_error": exchange_warning or inspected["debug_warning"],
        "created_at": (existing or {}).get("created_at") or now,
        "updated_at": now,
    }

    with _connect() as conn:
        conn.execute(
            """
            INSERT INTO meta_user_tokens (
                id, label, credential_type, business_ids,
                encrypted_token, token_fingerprint, graph_version,
                meta_user_id, meta_user_name, meta_app_id, token_type,
                expires_at, data_access_expires_at, status, auto_sync,
                check_interval_minutes, last_checked_at, last_sync_at,
                last_error, created_at, updated_at
            ) VALUES (
                :id, :label, :credential_type, :business_ids,
                :encrypted_token, :token_fingerprint, :graph_version,
                :meta_user_id, :meta_user_name, :meta_app_id, :token_type,
                :expires_at, :data_access_expires_at, :status, :auto_sync,
                :check_interval_minutes, :last_checked_at, :last_sync_at,
                :last_error, :created_at, :updated_at
            )
            ON CONFLICT(id) DO UPDATE SET
                label = excluded.label,
                credential_type = excluded.credential_type,
                business_ids = excluded.business_ids,
                encrypted_token = excluded.encrypted_token,
                token_fingerprint = excluded.token_fingerprint,
                graph_version = excluded.graph_version,
                meta_user_id = excluded.meta_user_id,
                meta_user_name = excluded.meta_user_name,
                meta_app_id = excluded.meta_app_id,
                token_type = excluded.token_type,
                expires_at = excluded.expires_at,
                data_access_expires_at = excluded.data_access_expires_at,
                status = excluded.status,
                auto_sync = excluded.auto_sync,
                check_interval_minutes = excluded.check_interval_minutes,
                last_checked_at = excluded.last_checked_at,
                last_error = excluded.last_error,
                updated_at = excluded.updated_at
            """,
            data,
        )
        conn.commit()

    saved = get_meta_user_token(data["id"])
    saved["exchanged_long_lived"] = exchanged
    saved["app_credentials_configured"] = bool(META_APP_ID and META_APP_SECRET)
    return saved


def _sanitize_meta_page(
    page,
    include_token=False,
    source="me_accounts",
    business_id="",
    business_name="",
):
    tasks = page.get("tasks") or []
    data = {
        "page_id": str(page.get("id") or ""),
        "name": page.get("name") or "",
        "meta_category": page.get("category") or "",
        "meta_tasks": tasks if isinstance(tasks, list) else [],
        "has_page_access_token": bool(page.get("access_token")),
        "meta_sources": [source] if source else [],
        "meta_business_ids": [business_id] if business_id else [],
        "meta_business_names": [business_name] if business_name else [],
    }
    if include_token:
        data["page_access_token"] = page.get("access_token") or ""
    return data


def _merge_meta_page(existing, incoming):
    if not existing:
        return incoming

    merged = dict(existing)
    for key in ["name", "meta_category"]:
        if not merged.get(key) and incoming.get(key):
            merged[key] = incoming[key]
    if incoming.get("page_access_token") and not merged.get("page_access_token"):
        merged["page_access_token"] = incoming["page_access_token"]
    merged["has_page_access_token"] = bool(merged.get("page_access_token"))

    for key in ["meta_tasks", "meta_sources", "meta_business_ids", "meta_business_names"]:
        values = []
        for value in list(merged.get(key) or []) + list(incoming.get(key) or []):
            if value and value not in values:
                values.append(value)
        merged[key] = values
    return merged


def _collect_meta_page_inventory(
    access_token,
    graph_version=None,
    include_token=False,
    credential_type="user_oauth",
    business_ids=None,
    system_user_id=None,
):
    fields = "id,name,access_token,tasks,category"
    credential_type = _normalize_credential_type(credential_type)
    configured_business_ids = _normalize_business_ids(business_ids)
    warnings = []
    businesses = []
    raw_entries = []
    source_counts = {
        "me_accounts": 0,
        "system_user_assigned_pages": 0,
        "business_owned_pages": 0,
        "business_client_pages": 0,
    }

    complete = True
    if credential_type == "system_user":
        assigned_system_user_id = str(system_user_id or "").strip()
        if not assigned_system_user_id:
            identity = _graph_get(
                "me",
                access_token,
                {"fields": "id,name"},
                graph_version=graph_version,
            )
            assigned_system_user_id = str(identity.get("id") or "").strip()
        if not assigned_system_user_id:
            raise ValueError("Cannot resolve Meta System User ID")

        primary_business_id = configured_business_ids[0] if configured_business_ids else ""
        primary_business_name = primary_business_id
        assigned_pages = _graph_collect(
            f"{assigned_system_user_id}/assigned_pages",
            access_token,
            {"fields": fields, "limit": 100},
            graph_version=graph_version,
        )
        source_counts["system_user_assigned_pages"] = len(assigned_pages)
        raw_entries.extend(
            (
                page,
                "system_user_assigned_pages",
                primary_business_id,
                primary_business_name,
            )
            for page in assigned_pages
        )
    else:
        direct_pages = _graph_collect(
            "me/accounts",
            access_token,
            {"fields": fields, "limit": 100},
            graph_version=graph_version,
        )
        source_counts["me_accounts"] = len(direct_pages)
        raw_entries.extend((page, "me_accounts", "", "") for page in direct_pages)

    if configured_business_ids:
        businesses = [
            {"id": business_id, "name": business_id}
            for business_id in configured_business_ids
        ]
    else:
        try:
            businesses = _graph_collect(
                "me/businesses",
                access_token,
                {"fields": "id,name", "limit": 100},
                graph_version=graph_version,
            )
        except ValueError as error:
            complete = False
            warnings.append(f"Cannot list Business Managers: {error}")

    if credential_type != "system_user":
        for business in businesses:
            business_id = str(business.get("id") or "")
            business_name = business.get("name") or business_id
            if not business_id:
                continue

            for edge, source in [
                ("owned_pages", "business_owned_pages"),
                ("client_pages", "business_client_pages"),
            ]:
                try:
                    business_pages = _graph_collect(
                        f"{business_id}/{edge}",
                        access_token,
                        {"fields": fields, "limit": 100},
                        graph_version=graph_version,
                    )
                    source_counts[source] += len(business_pages)
                    raw_entries.extend(
                        (page, source, business_id, business_name)
                        for page in business_pages
                    )
                except ValueError as error:
                    complete = False
                    warnings.append(f"{business_name}/{edge}: {error}")

    page_map = {}
    for raw_page, source, business_id, business_name in raw_entries:
        page = _sanitize_meta_page(
            raw_page,
            include_token=include_token,
            source=source,
            business_id=business_id,
            business_name=business_name,
        )
        if not page["page_id"]:
            continue
        page_map[page["page_id"]] = _merge_meta_page(
            page_map.get(page["page_id"]),
            page,
        )

    if include_token:
        for page_id, page in page_map.items():
            if page.get("page_access_token"):
                continue
            try:
                detail = _graph_get(
                    page_id,
                    access_token,
                    {"fields": fields},
                    graph_version=graph_version,
                )
                hydrated = _sanitize_meta_page(
                    detail,
                    include_token=True,
                    source="",
                )
                if (
                    credential_type == "system_user"
                    and not hydrated.get("page_access_token")
                    and str(detail.get("id") or "") == page_id
                ):
                    hydrated["page_access_token"] = access_token
                    hydrated["has_page_access_token"] = True
                page_map[page_id] = _merge_meta_page(page, hydrated)
            except ValueError as error:
                complete = False
                warnings.append(f"{page.get('name') or page_id}/page_token: {error}")

    pages = sorted(page_map.values(), key=lambda item: item.get("name", "").casefold())
    return {
        "pages": pages,
        "count": len(pages),
        "businesses": len(businesses),
        "source_counts": source_counts,
        "warnings": warnings,
        "complete": complete,
    }


def fetch_meta_pages(access_token, graph_version=None):
    return _collect_meta_page_inventory(
        access_token,
        graph_version=graph_version,
        include_token=False,
    )


def _refresh_fanpage_token_from_links(conn, fanpage_id, checked_at=None):
    link = conn.execute(
        """
        SELECT link.encrypted_page_token,
               token.status AS user_token_status
        FROM fanpages page
        JOIN meta_token_page_links link
          ON link.fanpage_id = page.id
         AND link.token_id = page.credential_id
        JOIN meta_user_tokens token ON token.id = link.token_id
        WHERE page.id = ?
          AND COALESCE(link.encrypted_page_token, '') != ''
          AND link.page_token_status = 'valid'
        LIMIT 1
        """,
        (fanpage_id,),
    ).fetchone()
    now = checked_at or _now()
    if link:
        page_token = _decrypt_secret(link["encrypted_page_token"])
        access_status = "connected" if link["user_token_status"] == "valid" else "degraded"
        conn.execute(
            """
            UPDATE fanpages
            SET page_access_token = ?,
                access_status = ?,
                is_enabled = 1,
                token_last_checked_at = ?,
                page_token_status = 'valid',
                page_token_last_checked_at = ?,
                page_token_last_error = '',
                updated_at = ?
            WHERE id = ?
            """,
            (page_token, access_status, now, now, now, fanpage_id),
        )
        return True

    latest_failure = conn.execute(
        """
        SELECT page_token_status,
               page_token_last_checked_at,
               page_token_last_error
        FROM meta_token_page_links link
        JOIN fanpages page
          ON page.id = link.fanpage_id
         AND page.credential_id = link.token_id
        WHERE page.id = ?
        LIMIT 1
        """,
        (fanpage_id,),
    ).fetchone()
    failure_status = (
        latest_failure["page_token_status"]
        if latest_failure and latest_failure["page_token_status"] in {"invalid", "error"}
        else "invalid"
    )
    failure_checked_at = (
        latest_failure["page_token_last_checked_at"]
        if latest_failure and latest_failure["page_token_last_checked_at"]
        else now
    )
    failure_error = (
        latest_failure["page_token_last_error"]
        if latest_failure
        else "No valid Page access token"
    )
    conn.execute(
        """
        UPDATE fanpages
        SET page_access_token = '',
            access_status = 'missing_page_token',
            is_enabled = 0,
            token_last_checked_at = ?,
            page_token_status = ?,
            page_token_last_checked_at = ?,
            page_token_last_error = ?,
            updated_at = ?
        WHERE id = ?
        """,
        (
            now,
            failure_status,
            failure_checked_at,
            failure_error or "",
            now,
            fanpage_id,
        ),
    )
    return False


def _validate_linked_page_token(page_id, encrypted_page_token, graph_version=None):
    encrypted = str(encrypted_page_token or "").strip()
    if not encrypted:
        return False, "", "Missing stored Page access token"

    try:
        page_token = _decrypt_secret(encrypted)
        payload = _graph_get(
            page_id,
            page_token,
            {"fields": "id,name"},
            graph_version=graph_version,
        )
        if str(payload.get("id") or "") != str(page_id or ""):
            return False, "", "Page token returned a different Page identity"
        return True, page_token, ""
    except Exception as error:
        return False, "", str(error)


def _page_token_failure_status(error):
    message = str(error or "").lower()
    invalid_markers = [
        "code 190",
        "invalid oauth",
        "expired",
        "session has been invalidated",
        "error validating access token",
        "missing stored page access token",
    ]
    return "invalid" if any(marker in message for marker in invalid_markers) else "error"


def _update_pages_after_user_token_expired(conn, token_id, graph_version, checked_at=None):
    rows = conn.execute(
        """
        SELECT page.id AS fanpage_id,
               page.page_id,
               link.encrypted_page_token
        FROM meta_token_page_links link
        JOIN fanpages page ON page.id = link.fanpage_id
        WHERE link.token_id = ?
        """,
        (token_id,),
    ).fetchall()
    now = checked_at or _now()
    results = []

    for row in rows:
        is_valid, page_token, error = _validate_linked_page_token(
            row["page_id"],
            row["encrypted_page_token"],
            graph_version=graph_version,
        )
        if is_valid:
            conn.execute(
                """
                UPDATE meta_token_page_links
                SET page_token_status = 'valid',
                    page_token_last_checked_at = ?,
                    page_token_last_error = '',
                    updated_at = ?
                WHERE token_id = ? AND fanpage_id = ?
                """,
                (now, now, token_id, row["fanpage_id"]),
            )
        else:
            failure_status = _page_token_failure_status(error)
            conn.execute(
                """
                UPDATE meta_token_page_links
                SET page_token_status = ?,
                    page_token_last_checked_at = ?,
                    page_token_last_error = ?,
                    updated_at = ?
                WHERE token_id = ? AND fanpage_id = ?
                """,
                (failure_status, now, error, now, token_id, row["fanpage_id"]),
            )
        _refresh_fanpage_token_from_links(conn, row["fanpage_id"], checked_at=now)
        results.append({
            "fanpage_id": row["fanpage_id"],
            "page_id": row["page_id"],
            "page_token_valid": is_valid,
            "error": error,
        })

    return results


def check_fanpage_page_token(fanpage_id, token_id=None):
    init_auto_reup_db()
    now = _now()

    with _connect() as conn:
        page = conn.execute(
            "SELECT id, page_id, credential_id FROM fanpages WHERE id = ?",
            (fanpage_id,),
        ).fetchone()
        if not page:
            raise ValueError("Fanpage not found")

        selected_token_id = token_id or page["credential_id"]
        if not selected_token_id:
            raise ValueError("Page has no assigned operational credential")
        params = [fanpage_id, selected_token_id]

        link = conn.execute(
            """
            SELECT link.token_id,
                   link.encrypted_page_token,
                   token.graph_version,
                   token.status AS user_token_status
            FROM meta_token_page_links link
            JOIN meta_user_tokens token ON token.id = link.token_id
            WHERE link.fanpage_id = ?
              AND link.token_id = ?
            LIMIT 1
            """,
            tuple(params),
        ).fetchone()
        if not link:
            raise ValueError("Page is not linked to the selected Meta account")

        is_valid, _, error = _validate_linked_page_token(
            page["page_id"],
            link["encrypted_page_token"],
            graph_version=link["graph_version"] or None,
        )
        page_token_status = "valid" if is_valid else _page_token_failure_status(error)
        conn.execute(
            """
            UPDATE meta_token_page_links
            SET page_token_status = ?,
                page_token_last_checked_at = ?,
                page_token_last_error = ?,
                updated_at = ?
            WHERE token_id = ? AND fanpage_id = ?
            """,
            (
                page_token_status,
                now,
                "" if is_valid else error,
                now,
                link["token_id"],
                fanpage_id,
            ),
        )
        _refresh_fanpage_token_from_links(conn, fanpage_id, checked_at=now)
        conn.commit()

    return {
        "page": get_page(fanpage_id),
        "token_id": link["token_id"],
        "page_token_valid": is_valid,
        "page_token_status": page_token_status,
        "checked_at": now,
        "error": "" if is_valid else error,
    }


def _delete_fanpages(conn, fanpage_ids):
    ids = sorted({str(value) for value in fanpage_ids if value})
    if not ids:
        return 0

    placeholders = ",".join("?" for _ in ids)
    for table in ["reup_actions", "reup_sources", "reup_jobs"]:
        conn.execute(
            f"UPDATE {table} SET target_page_id = NULL WHERE target_page_id IN ({placeholders})",
            tuple(ids),
        )
    conn.execute(
        f"DELETE FROM meta_token_page_links WHERE fanpage_id IN ({placeholders})",
        tuple(ids),
    )
    return conn.execute(
        f"DELETE FROM fanpages WHERE id IN ({placeholders})",
        tuple(ids),
    ).rowcount


def _cleanup_orphan_meta_pages(conn, candidate_ids=None):
    params = []
    candidate_sql = ""
    if candidate_ids is not None:
        ids = sorted({str(value) for value in candidate_ids if value})
        if not ids:
            return 0
        candidate_sql = f" AND page.id IN ({','.join('?' for _ in ids)})"
        params.extend(ids)

    rows = conn.execute(
        f"""
        SELECT page.id
        FROM fanpages page
        WHERE COALESCE(page.token_source, '') != ''
          AND NOT EXISTS (
              SELECT 1
              FROM meta_token_page_links link
              WHERE link.fanpage_id = page.id
          )
          {candidate_sql}
        """,
        tuple(params),
    ).fetchall()
    return _delete_fanpages(conn, [row["id"] for row in rows])


def import_meta_pages(
    access_token,
    graph_version=None,
    token_id=None,
    credential_type="user_oauth",
    business_ids=None,
    system_user_id=None,
):
    inventory = _collect_meta_page_inventory(
        access_token,
        graph_version=graph_version,
        include_token=True,
        credential_type=credential_type,
        business_ids=business_ids,
        system_user_id=system_user_id,
    )
    raw_pages = inventory["pages"]

    init_auto_reup_db()
    now = _now()
    imported = 0
    updated = 0
    stale = 0
    imported_pages = []
    seen_page_ids = set()

    with _connect() as conn:
        for page in raw_pages:
            if not page["page_id"] or not page["name"]:
                continue
            seen_page_ids.add(page["page_id"])

            existing = conn.execute(
                """
                SELECT id, page_access_token, credential_id, access_status, is_enabled
                FROM fanpages
                WHERE page_id = ?
                """,
                (page["page_id"],),
            ).fetchone()
            credential_id = (existing["credential_id"] if existing else "") or token_id or ""
            owns_page = not token_id or credential_id == token_id
            page_token = (
                page["page_access_token"]
                if owns_page and page["page_access_token"]
                else (existing["page_access_token"] if existing else "")
            )
            data = {
                "id": existing["id"] if existing else _new_id(),
                "name": page["name"],
                "page_id": page["page_id"],
                "access_status": "connected" if page_token else "missing_page_token",
                "is_enabled": 1 if page_token else 0,
                "daily_limit": 3,
                "active_from": "09:00",
                "active_to": "22:30",
                "min_gap_minutes": 180,
                "default_template_id": "",
                "notes": "",
                "page_access_token": page_token,
                "meta_tasks": json.dumps(page["meta_tasks"], ensure_ascii=False),
                "meta_category": page["meta_category"],
                "meta_sources": json.dumps(page["meta_sources"], ensure_ascii=False),
                "meta_business_ids": json.dumps(page["meta_business_ids"], ensure_ascii=False),
                "meta_business_names": json.dumps(page["meta_business_names"], ensure_ascii=False),
                "meta_last_seen_at": now,
                "connected_at": now,
                "token_source": ",".join(page["meta_sources"]) or "meta_import",
                "token_last_checked_at": now,
                "page_token_status": "valid" if page_token else "invalid",
                "page_token_last_checked_at": now,
                "page_token_last_error": "" if page_token else "Missing Page access token",
                "credential_id": credential_id,
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
                        meta_sources = :meta_sources,
                        meta_business_ids = :meta_business_ids,
                        meta_business_names = :meta_business_names,
                        meta_last_seen_at = :meta_last_seen_at,
                        connected_at = :connected_at,
                        token_source = :token_source,
                        token_last_checked_at = :token_last_checked_at,
                        page_token_status = :page_token_status,
                        page_token_last_checked_at = :page_token_last_checked_at,
                        page_token_last_error = :page_token_last_error,
                        credential_id = :credential_id,
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
                        meta_sources, meta_business_ids, meta_business_names,
                        meta_last_seen_at, connected_at, token_source,
                        token_last_checked_at, page_token_status,
                        page_token_last_checked_at, page_token_last_error,
                        credential_id,
                        created_at, updated_at
                    ) VALUES (
                        :id, :name, :page_id, :access_status, :is_enabled, :daily_limit,
                        :active_from, :active_to, :min_gap_minutes, :default_template_id,
                        :notes, :page_access_token, :meta_tasks, :meta_category,
                        :meta_sources, :meta_business_ids, :meta_business_names,
                        :meta_last_seen_at, :connected_at, :token_source,
                        :token_last_checked_at, :page_token_status,
                        :page_token_last_checked_at, :page_token_last_error,
                        :credential_id,
                        :created_at, :updated_at
                    )
                    """,
                    data,
                )
                imported += 1

            row = conn.execute("SELECT * FROM fanpages WHERE id = ?", (data["id"],)).fetchone()
            imported_pages.append(_row_to_dict(row))

            if token_id:
                conn.execute(
                    """
                    INSERT INTO meta_token_page_links (
                        token_id, fanpage_id, encrypted_page_token, meta_sources,
                        meta_business_ids, meta_business_names, last_seen_at,
                        page_token_status, page_token_last_checked_at,
                        page_token_last_error, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(token_id, fanpage_id) DO UPDATE SET
                        encrypted_page_token = excluded.encrypted_page_token,
                        meta_sources = excluded.meta_sources,
                        meta_business_ids = excluded.meta_business_ids,
                        meta_business_names = excluded.meta_business_names,
                        last_seen_at = excluded.last_seen_at,
                        page_token_status = excluded.page_token_status,
                        page_token_last_checked_at = excluded.page_token_last_checked_at,
                        page_token_last_error = excluded.page_token_last_error,
                        updated_at = excluded.updated_at
                    """,
                    (
                        token_id,
                        data["id"],
                        _encrypt_secret(page["page_access_token"]),
                        data["meta_sources"],
                        data["meta_business_ids"],
                        data["meta_business_names"],
                        now,
                        "valid" if page["page_access_token"] else "invalid",
                        now,
                        "" if page["page_access_token"] else "Missing Page access token",
                        now,
                        now,
                    ),
                )

        if token_id and inventory["complete"]:
            linked_rows = conn.execute(
                "SELECT fanpage_id FROM meta_token_page_links WHERE token_id = ?",
                (token_id,),
            ).fetchall()
            linked_ids = {row["fanpage_id"] for row in linked_rows}
            current_ids = {
                row["id"]
                for row in conn.execute(
                    f"SELECT id FROM fanpages WHERE page_id IN ({','.join('?' for _ in seen_page_ids)})",
                    tuple(sorted(seen_page_ids)),
                ).fetchall()
            } if seen_page_ids else set()
            removed_link_ids = linked_ids - current_ids
            removed_operational_ids = []
            for fanpage_id in removed_link_ids:
                page_owner = conn.execute(
                    "SELECT credential_id FROM fanpages WHERE id = ?",
                    (fanpage_id,),
                ).fetchone()
                if page_owner and page_owner["credential_id"] == token_id:
                    removed_operational_ids.append(fanpage_id)
                    continue
                conn.execute(
                    "DELETE FROM meta_token_page_links WHERE token_id = ? AND fanpage_id = ?",
                    (token_id, fanpage_id),
                )
                _refresh_fanpage_token_from_links(conn, fanpage_id, checked_at=now)
            _delete_fanpages(conn, removed_operational_ids)
            stale = len(removed_link_ids)
        elif not token_id and inventory["complete"]:
            if seen_page_ids:
                placeholders = ",".join("?" for _ in seen_page_ids)
                stale = conn.execute(
                    f"""
                    UPDATE fanpages
                    SET access_status = 'stale',
                        is_enabled = 0,
                        token_last_checked_at = ?,
                        updated_at = ?
                    WHERE COALESCE(token_source, '') != ''
                      AND page_id NOT IN ({placeholders})
                    """,
                    (now, now, *sorted(seen_page_ids)),
                ).rowcount
            else:
                stale = conn.execute(
                    """
                    UPDATE fanpages
                    SET access_status = 'stale',
                        is_enabled = 0,
                        token_last_checked_at = ?,
                        updated_at = ?
                    WHERE COALESCE(token_source, '') != ''
                    """,
                    (now, now),
                ).rowcount

        conn.commit()

    return {
        "imported": imported,
        "updated": updated,
        "stale": stale,
        "pages": imported_pages,
        "count": len(imported_pages),
        "businesses": inventory["businesses"],
        "source_counts": inventory["source_counts"],
        "warnings": inventory["warnings"],
        "complete": inventory["complete"],
    }


def sync_meta_user_token(token_id):
    with _TOKEN_SYNC_LOCK:
        token_record = get_meta_user_token(token_id, include_secret=True)
        access_token = token_record["access_token"]
        graph_version = token_record.get("graph_version") or GRAPH_API_VERSION
        now = _now()

        try:
            inspected = _inspect_meta_user_token(
                access_token,
                graph_version=graph_version,
            )
            result = import_meta_pages(
                access_token,
                graph_version=graph_version,
                token_id=token_id,
                credential_type=token_record.get("credential_type") or "user_oauth",
                business_ids=token_record.get("business_ids") or [],
                system_user_id=inspected.get("meta_user_id") or token_record.get("meta_user_id"),
            )
            with _connect() as conn:
                conn.execute(
                    """
                    UPDATE meta_user_tokens
                    SET meta_user_id = ?,
                        meta_user_name = ?,
                        meta_app_id = ?,
                        token_type = ?,
                        expires_at = ?,
                        data_access_expires_at = ?,
                        status = 'valid',
                        last_checked_at = ?,
                        last_sync_at = ?,
                        last_error = ?,
                        updated_at = ?
                    WHERE id = ?
                    """,
                    (
                        inspected["meta_user_id"],
                        inspected["meta_user_name"],
                        inspected["meta_app_id"],
                        inspected["token_type"],
                        inspected["expires_at"],
                        inspected["data_access_expires_at"],
                        now,
                        now,
                        inspected["debug_warning"],
                        now,
                        token_id,
                    ),
                )
                conn.commit()
            result["token"] = get_meta_user_token(token_id)
            return result
        except Exception as error:
            message = str(error)
            lowered = message.lower()
            status = "expired" if any(
                marker in lowered
                for marker in ["expired", "code 190", "subcode 463", "invalid oauth"]
            ) else "error"
            with _connect() as conn:
                conn.execute(
                    """
                    UPDATE meta_user_tokens
                    SET status = ?,
                        last_checked_at = ?,
                        last_error = ?,
                        updated_at = ?
                    WHERE id = ?
                    """,
                    (status, now, message, now, token_id),
                )
                if status == "expired":
                    page_checks = _update_pages_after_user_token_expired(
                        conn,
                        token_id,
                        graph_version,
                        checked_at=now,
                    )
                    valid_count = sum(
                        1 for item in page_checks if item["page_token_valid"]
                    )
                    invalid_count = len(page_checks) - valid_count
                    conn.execute(
                        """
                        UPDATE meta_user_tokens
                        SET last_error = ?
                        WHERE id = ?
                        """,
                        (
                            f"{message} | Page tokens: "
                            f"{valid_count} usable, {invalid_count} invalid. Re-auth required.",
                            token_id,
                        ),
                    )
                conn.commit()
            raise


def update_meta_user_token(token_id, payload, validate=True):
    existing = get_meta_user_token(token_id, include_secret=True)
    if payload.get("access_token"):
        saved = save_meta_user_token(payload, token_id=token_id, validate=validate)
    else:
        updates = {}
        if "label" in payload:
            updates["label"] = str(payload.get("label") or "").strip() or existing["label"]
        if "auto_sync" in payload:
            updates["auto_sync"] = 1 if payload.get("auto_sync") else 0
        if "check_interval_minutes" in payload:
            updates["check_interval_minutes"] = max(
                15,
                int(payload.get("check_interval_minutes") or 360),
            )
        if "graph_version" in payload:
            updates["graph_version"] = str(payload.get("graph_version") or "").strip()
        if "credential_type" in payload:
            updates["credential_type"] = _normalize_credential_type(
                payload.get("credential_type")
            )
        if "business_ids" in payload:
            business_ids = _normalize_business_ids(payload.get("business_ids"))
            credential_type = updates.get(
                "credential_type",
                existing.get("credential_type") or "user_oauth",
            )
            if credential_type == "system_user" and not business_ids:
                raise ValueError("System User credential requires at least one Business ID")
            updates["business_ids"] = json.dumps(business_ids, ensure_ascii=False)
        if updates:
            updates["updated_at"] = _now()
            updates["id"] = token_id
            assignments = ", ".join(f"{key} = :{key}" for key in updates if key != "id")
            with _connect() as conn:
                conn.execute(
                    f"UPDATE meta_user_tokens SET {assignments} WHERE id = :id",
                    updates,
                )
                conn.commit()
        saved = get_meta_user_token(token_id)
    return saved


def delete_meta_user_token(token_id):
    init_auto_reup_db()
    with _TOKEN_SYNC_LOCK, _connect() as conn:
        linked = conn.execute(
            "SELECT fanpage_id FROM meta_token_page_links WHERE token_id = ?",
            (token_id,),
        ).fetchall()
        operational = conn.execute(
            "SELECT id FROM fanpages WHERE credential_id = ?",
            (token_id,),
        ).fetchall()
        operational_ids = [row["id"] for row in operational]

        # A credential owns its operational Page group. Removing credential A
        # removes A Pages entirely; another credential never inherits them
        # implicitly even if Meta exposed an overlapping Page link.
        _delete_fanpages(conn, operational_ids)
        conn.execute(
            "DELETE FROM meta_token_page_links WHERE token_id = ?",
            (token_id,),
        )
        deleted = conn.execute(
            "DELETE FROM meta_user_tokens WHERE id = ?",
            (token_id,),
        ).rowcount
        _cleanup_orphan_meta_pages(
            conn,
            candidate_ids=[row["fanpage_id"] for row in linked],
        )
        conn.commit()
    return bool(deleted)


def sync_due_meta_user_tokens(force=False):
    results = []
    for token in list_meta_user_tokens():
        if not force and not _token_due(token):
            continue
        try:
            result = sync_meta_user_token(token["id"])
            results.append({
                "id": token["id"],
                "label": token["label"],
                "success": True,
                "count": result.get("count", 0),
            })
        except Exception as error:
            results.append({
                "id": token["id"],
                "label": token["label"],
                "success": False,
                "error": str(error),
            })
    return results


def _sync_meta_user_token_worker(token_id):
    try:
        sync_meta_user_token(token_id)
    finally:
        with _TOKEN_SYNC_REQUEST_LOCK:
            _TOKEN_SYNCS_RUNNING.discard(token_id)


def request_meta_user_token_sync(token_id):
    get_meta_user_token(token_id)
    with _TOKEN_SYNC_REQUEST_LOCK:
        if token_id in _TOKEN_SYNCS_RUNNING:
            return {"id": token_id, "started": False, "reason": "already_running"}
        _TOKEN_SYNCS_RUNNING.add(token_id)

    thread = threading.Thread(
        target=_sync_meta_user_token_worker,
        args=(token_id,),
        name=f"meta-token-sync-{token_id[:8]}",
        daemon=True,
    )
    thread.start()
    return {"id": token_id, "started": True}


def request_due_meta_user_token_syncs(force=False):
    results = []
    for token in list_meta_user_tokens():
        if not force and not _token_due(token):
            continue
        try:
            queued = request_meta_user_token_sync(token["id"])
            queued["label"] = token["label"]
            results.append(queued)
        except Exception as error:
            results.append({
                "id": token["id"],
                "label": token["label"],
                "started": False,
                "error": str(error),
            })
    return results


def _token_monitor_loop():
    while not _TOKEN_MONITOR_STOP.wait(TOKEN_MONITOR_INTERVAL_SECONDS):
        try:
            request_due_meta_user_token_syncs()
        except Exception:
            pass


def start_meta_token_monitor():
    global _TOKEN_MONITOR_THREAD
    init_auto_reup_db()
    if _TOKEN_MONITOR_THREAD and _TOKEN_MONITOR_THREAD.is_alive():
        return
    _TOKEN_MONITOR_STOP.clear()
    _TOKEN_MONITOR_THREAD = threading.Thread(
        target=_token_monitor_loop,
        name="meta-token-monitor",
        daemon=True,
    )
    _TOKEN_MONITOR_THREAD.start()


def stop_meta_token_monitor():
    _TOKEN_MONITOR_STOP.set()


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
    actions = [_row_to_dict(row) for row in rows]
    for action in actions:
        with _connect() as conn:
            action["reup_target_total"] = _reup_target_total_for_action(conn, action)
        if action.get("target_page_id"):
            action["page_insights"] = get_page_insight_snapshots(action["target_page_id"])
    return actions


def _normalize_schedule_mode(value):
    mode = str(value or "random_interval").strip().lower()
    aliases = {
        "random": "random_interval",
        "interval": "random_interval",
        "manual": "manual_times",
        "fixed": "manual_times",
        "smart": "smart_daily",
        "auto": "smart_daily",
    }
    mode = aliases.get(mode, mode)
    if mode not in SCHEDULE_MODES:
        raise ValueError("Unsupported schedule mode")
    return mode


def _normalize_smart_profile(value):
    profile = str(value or "vn").strip().lower()
    aliases = {
        "vietnam": "vn",
        "viet": "vn",
        "usa": "us",
        "america": "us",
        "my": "us",
    }
    profile = aliases.get(profile, profile)
    if profile not in SMART_PROFILES:
        raise ValueError("Unsupported golden-hour profile")
    return profile


def _clock_to_minutes(value):
    hour, minute = _parse_clock(value, (0, 0))
    return hour * 60 + minute


def _minutes_to_clock(value):
    minutes = int(value) % (24 * 60)
    return f"{minutes // 60:02d}:{minutes % 60:02d}"


def _normalize_manual_times(value, daily_limit):
    if isinstance(value, str):
        decoded = _decode_json(value, [])
        values = decoded if isinstance(decoded, list) else re.split(r"[\s,;]+", value)
    elif isinstance(value, (list, tuple)):
        values = value
    else:
        values = []

    normalized = []
    for item in values:
        raw = str(item or "").strip()
        if not raw:
            continue
        normalized.append(_minutes_to_clock(_clock_to_minutes(raw)))

    if len(normalized) != daily_limit:
        raise ValueError("Manual schedule must contain exactly one time for each daily post")
    if len(set(normalized)) != len(normalized):
        raise ValueError("Manual schedule times must not be duplicated")
    return sorted(normalized, key=_clock_to_minutes)


def _validate_action_configuration(payload, current=None):
    merged = dict(current or {})
    merged.update({key: value for key, value in payload.items() if value is not None})

    target_page_id = str(merged.get("target_page_id") or "").strip()
    if not target_page_id:
        raise ValueError("Select a destination fanpage")

    page = get_page(target_page_id)
    target_changed = (
        current is None
        or (
            "target_page_id" in payload
            and str(payload.get("target_page_id") or "") != str((current or {}).get("target_page_id") or "")
        )
    )
    enabling_action = payload.get("enabled") is True
    require_operational_page = current is None or target_changed or enabling_action
    if require_operational_page and (
        not page.get("has_page_access_token") or page.get("page_token_status") != "valid"
    ):
        raise ValueError("Destination fanpage does not have a valid Page access token")
    apply_frame = bool(merged.get("apply_frame"))
    template_id = str(merged.get("template_id") or "").strip()

    if apply_frame and not template_id:
        raise ValueError("Select a frame template before enabling Creative Frame")
    if template_id:
        load_frame_template(template_id)

    daily_limit = max(1, min(50, int(merged.get("daily_limit") or 3)))
    schedule_mode = _normalize_schedule_mode(merged.get("schedule_mode"))
    smart_profile = _normalize_smart_profile(merged.get("smart_profile"))
    jitter_minutes = max(0, min(45, int(merged.get("jitter_minutes") or 15)))
    min_gap = max(15, int(merged.get("min_gap_minutes") or 180))
    max_gap = max(15, int(merged.get("max_gap_minutes") or min_gap))
    if max_gap < min_gap:
        raise ValueError("Maximum random interval must be greater than or equal to minimum interval")
    raw_manual_times = merged.get("manual_times")
    manual_times = (
        raw_manual_times
        if isinstance(raw_manual_times, list)
        else _decode_json(raw_manual_times, [])
    )
    if schedule_mode == "manual_times":
        manual_times = _normalize_manual_times(manual_times, daily_limit)

    return {
        "page": page,
        "name": page["name"],
        "template_id": template_id,
        "daily_limit": daily_limit,
        "schedule_mode": schedule_mode,
        "manual_times": manual_times,
        "smart_profile": smart_profile,
        "jitter_minutes": jitter_minutes,
        "min_gap_minutes": min_gap,
        "max_gap_minutes": max_gap,
    }


def create_action(payload):
    init_auto_reup_db()
    now = _now()
    validated = _validate_action_configuration(payload)
    data = {
        "id": _new_id(),
        "name": validated["name"],
        "target_page_id": payload.get("target_page_id") or None,
        "platform": (payload.get("platform") or "facebook").strip(),
        "source_url": payload.get("source_url", "").strip(),
        "template_id": validated["template_id"],
        "translate_caption": 1 if payload.get("translate_caption", True) else 0,
        "apply_frame": 1 if payload.get("apply_frame") else 0,
        "creative_remove_source_audio": 1 if payload.get("creative_remove_source_audio", True) else 0,
        "creative_randomize_variant": 1 if payload.get("creative_randomize_variant", True) else 0,
        "creative_smart_audio": 1 if payload.get("creative_smart_audio", True) else 0,
        "creative_audio_volume": max(0.02, min(2.0, float(payload.get("creative_audio_volume") or 1.0))),
        "creative_custom_audio_path": payload.get("creative_custom_audio_path") or "",
        "content_cleaner_enabled": 1 if payload.get("content_cleaner_enabled", True) else 0,
        "enabled": 1 if payload.get("enabled", True) else 0,
        "daily_limit": validated["daily_limit"],
        "active_from": payload.get("active_from") or "09:00",
        "active_to": payload.get("active_to") or "22:30",
        "min_gap_minutes": validated["min_gap_minutes"],
        "max_gap_minutes": validated["max_gap_minutes"],
        "schedule_mode": validated["schedule_mode"],
        "manual_times": json.dumps(validated["manual_times"], ensure_ascii=False),
        "smart_profile": validated["smart_profile"],
        "jitter_minutes": validated["jitter_minutes"],
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

    if not data["source_url"]:
        raise ValueError("Missing source URL")

    with _connect() as conn:
        conn.execute(
            """
            INSERT INTO reup_actions (
                id, name, target_page_id, platform, source_url, template_id,
                translate_caption, apply_frame, creative_remove_source_audio,
                creative_randomize_variant, creative_smart_audio, creative_audio_volume,
                creative_custom_audio_path, content_cleaner_enabled, enabled,
                daily_limit, active_from, active_to, min_gap_minutes, max_gap_minutes,
                schedule_mode, manual_times, smart_profile, jitter_minutes,
                scan_interval_minutes, progress_total, progress_scanned,
                progress_posted, progress_errors, last_scan_at, notes,
                created_at, updated_at
            ) VALUES (
                :id, :name, :target_page_id, :platform, :source_url, :template_id,
                :translate_caption, :apply_frame, :creative_remove_source_audio,
                :creative_randomize_variant, :creative_smart_audio, :creative_audio_volume,
                :creative_custom_audio_path, :content_cleaner_enabled, :enabled,
                :daily_limit, :active_from, :active_to, :min_gap_minutes, :max_gap_minutes,
                :schedule_mode, :manual_times, :smart_profile, :jitter_minutes,
                :scan_interval_minutes, :progress_total, :progress_scanned,
                :progress_posted, :progress_errors, :last_scan_at, :notes,
                :created_at, :updated_at
            )
            """,
            data,
        )
        conn.commit()

    _record_action_event(
        data["id"],
        "action_created",
        "Action da duoc tao va san sang quet nguon.",
    )
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
    current = get_action(action_id)
    validated = _validate_action_configuration(payload, current=current)
    allowed = {
        "name",
        "target_page_id",
        "platform",
        "source_url",
        "template_id",
        "translate_caption",
        "apply_frame",
        "creative_remove_source_audio",
        "creative_randomize_variant",
        "creative_smart_audio",
        "creative_audio_volume",
        "creative_custom_audio_path",
        "content_cleaner_enabled",
        "enabled",
        "daily_limit",
        "active_from",
        "active_to",
        "min_gap_minutes",
        "max_gap_minutes",
        "schedule_mode",
        "manual_times",
        "smart_profile",
        "jitter_minutes",
        "scan_interval_minutes",
        "progress_total",
        "progress_scanned",
        "progress_posted",
        "progress_errors",
        "last_scan_at",
        "notes",
    }
    updates = {key: value for key, value in payload.items() if key in allowed}
    updates["name"] = validated["name"]
    updates["template_id"] = validated["template_id"]
    updates["daily_limit"] = validated["daily_limit"]
    updates["min_gap_minutes"] = validated["min_gap_minutes"]
    updates["max_gap_minutes"] = validated["max_gap_minutes"]
    updates["schedule_mode"] = validated["schedule_mode"]
    updates["manual_times"] = json.dumps(validated["manual_times"], ensure_ascii=False)
    updates["smart_profile"] = validated["smart_profile"]
    updates["jitter_minutes"] = validated["jitter_minutes"]
    if not updates:
        return get_action(action_id)

    for boolean_key in [
        "translate_caption",
        "apply_frame",
        "creative_remove_source_audio",
        "creative_randomize_variant",
        "creative_smart_audio",
        "content_cleaner_enabled",
        "enabled",
    ]:
        if boolean_key in updates:
            updates[boolean_key] = 1 if updates[boolean_key] else 0

    if "creative_audio_volume" in updates and updates["creative_audio_volume"] is not None:
        updates["creative_audio_volume"] = max(0.02, min(2.0, float(updates["creative_audio_volume"] or 1.0)))

    for numeric_key in [
        "daily_limit",
        "min_gap_minutes",
        "max_gap_minutes",
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
        schedule_fields = {
            "target_page_id",
            "enabled",
            "daily_limit",
            "active_from",
            "active_to",
            "min_gap_minutes",
            "max_gap_minutes",
            "schedule_mode",
            "manual_times",
            "smart_profile",
            "jitter_minutes",
        }
        if schedule_fields.intersection(updates):
            conn.execute(
                """
                UPDATE reup_jobs
                SET scheduled_at = NULL,
                    updated_at = ?
                WHERE action_id = ?
                  AND status = 'ready'
                """,
                (_now(), action_id),
            )
        conn.commit()

    if "enabled" in updates:
        _record_action_event(
            action_id,
            "action_enabled" if updates["enabled"] else "action_paused",
            "Action da bat va tiep tuc xu ly."
            if updates["enabled"]
            else "Action da tam dung.",
        )
    elif schedule_fields.intersection(updates):
        _record_action_event(
            action_id,
            "schedule_updated",
            "Lich dang da thay doi; cac job cho dang se duoc xep lich lai.",
        )
    return get_action(action_id)


def render_action_video(
    action_id,
    video_path,
    output_dir=None,
    target_lang="vi",
    source_lang="en",
    translation_engine="argos",
    frame_fit=None,
    progress_callback=None,
):
    action = get_action(action_id)
    source_path = Path(str(video_path or "")).expanduser().resolve()
    if not source_path.is_file():
        raise FileNotFoundError(f"Missing source video: {source_path}")

    if not action["translate_caption"] and not action["apply_frame"]:
        raise ValueError("Action has no enabled video pipeline")

    if action["apply_frame"]:
        load_frame_template(action.get("template_id") or "")

    from app.services.render_service import render_single_video

    return render_single_video(
        video_path=str(source_path),
        output_dir=output_dir,
        target_lang=target_lang,
        source_lang=source_lang,
        languages=[source_lang],
        translation_engine=translation_engine,
        translate=bool(action["translate_caption"]),
        render_video=True,
        apply_creative_frame=bool(action["apply_frame"]),
        creative_frame_template_id=action.get("template_id") or None,
        creative_frame_fit=frame_fit,
        creative_remove_source_audio=bool(action.get("creative_remove_source_audio", True)),
        creative_randomize_variant=bool(action.get("creative_randomize_variant", True)),
        creative_smart_audio=bool(action.get("creative_smart_audio", True)),
        creative_audio_volume=float(action.get("creative_audio_volume") or 1.0),
        creative_custom_audio_path=action.get("creative_custom_audio_path") or None,
        progress_callback=progress_callback,
    )


def choose_action_gap_minutes(action_id):
    action = get_action(action_id)
    min_gap = max(1, int(action.get("min_gap_minutes") or 180))
    max_gap = max(min_gap, int(action.get("max_gap_minutes") or min_gap))
    return _SCHEDULE_RANDOM.randint(min_gap, max_gap)


def _update_job_runtime(job_id, **updates):
    allowed = {
        "status",
        "stage",
        "progress",
        "source_local_path",
        "output_path",
        "publish_id",
        "attempts",
        "scheduled_at",
        "posted_at",
        "raw_content",
        "clean_content",
        "removed_links",
        "removed_lines",
        "error",
    }
    values = {key: value for key, value in updates.items() if key in allowed}
    if not values:
        return
    event_relevant = bool(
        {"status", "stage", "scheduled_at", "posted_at", "error"}.intersection(values)
    )
    previous = None
    if event_relevant:
        with _connect() as conn:
            previous = conn.execute(
                """
                SELECT action_id, status, stage, scheduled_at, error
                FROM reup_jobs
                WHERE id = ?
                """,
                (job_id,),
            ).fetchone()
    if "progress" in values:
        values["progress"] = max(0, min(100, int(values["progress"] or 0)))
    values["updated_at"] = _now()
    assignments = ", ".join([f"{key} = :{key}" for key in values])
    values["id"] = job_id
    with _connect() as conn:
        conn.execute(f"UPDATE reup_jobs SET {assignments} WHERE id = :id", values)
        conn.commit()

    if not previous:
        return

    action_id = previous["action_id"]
    next_status = values.get("status", previous["status"])
    next_stage = values.get("stage", previous["stage"])
    stage_changed = next_stage != previous["stage"]
    status_changed = next_status != previous["status"]
    schedule_changed = (
        "scheduled_at" in values
        and values.get("scheduled_at") != previous["scheduled_at"]
    )
    if status_changed or stage_changed:
        event_type = f"job_{next_stage or next_status}"
        level = "error" if next_status == "error" else (
            "success" if next_status == "posted" else "info"
        )
        messages = {
            "download": "Bat dau tai video nguon.",
            "downloaded": "Da tai xong video nguon.",
            "render": "Dang xu ly pipeline video.",
            "ready": "Video da xu ly xong, dang cho lich dang.",
            "publishing": "Dang tai video len fanpage dich.",
            "posted": "Dang video thanh cong.",
            "prepare_error": "Xu ly video that bai.",
            "publish_error": "Dang video len Facebook that bai.",
            "queued": "Video da vao hang doi xu ly.",
        }
        _record_action_event(
            action_id,
            event_type,
            messages.get(next_stage, f"Job chuyen sang {next_stage or next_status}."),
            job_id=job_id,
            level=level,
            payload={
                "status": next_status,
                "stage": next_stage,
                "progress": values.get("progress"),
                "error": values.get("error") or "",
            },
        )
    if schedule_changed and values.get("scheduled_at"):
        _record_action_event(
            action_id,
            "job_scheduled",
            "Da xep lich cho lan dang tiep theo.",
            job_id=job_id,
            payload={"scheduled_at": values["scheduled_at"]},
        )


def _claim_next_queued_job():
    init_auto_reup_db()
    with _connect() as conn:
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute(
            """
            SELECT j.id
            FROM reup_jobs j
            JOIN reup_actions a ON a.id = j.action_id
            JOIN fanpages p ON p.id = j.target_page_id
            WHERE j.status = 'queued'
              AND a.enabled = 1
              AND p.is_enabled = 1
              AND p.page_token_status = 'valid'
              AND COALESCE(p.page_access_token, '') != ''
            ORDER BY j.created_at ASC
            LIMIT 1
            """
        ).fetchone()
        if not row:
            conn.commit()
            return None
        claimed = conn.execute(
            """
            UPDATE reup_jobs
            SET status = 'processing',
                stage = 'download',
                progress = 1,
                attempts = attempts + 1,
                error = '',
                updated_at = ?
            WHERE id = ? AND status = 'queued'
            """,
            (_now(), row["id"]),
        ).rowcount
        conn.commit()
    return row["id"] if claimed else None


def _job_work_dir(job_id):
    path = AUTO_REUP_JOB_DIR / str(job_id)
    path.mkdir(parents=True, exist_ok=True)
    return path


def _download_job_source(job, action):
    import yt_dlp

    work_dir = _job_work_dir(job["id"])
    for old_file in work_dir.glob("source.*"):
        if old_file.is_file():
            old_file.unlink()

    last_reported = -1

    def progress_hook(data):
        nonlocal last_reported
        status = data.get("status")
        if status == "finished":
            percent = 35
        else:
            total = data.get("total_bytes") or data.get("total_bytes_estimate") or 0
            downloaded = data.get("downloaded_bytes") or 0
            percent = 2 + int((downloaded / total) * 32) if total else 5
        if percent != last_reported:
            last_reported = percent
            _update_job_runtime(
                job["id"],
                stage="download",
                progress=percent,
            )

    options = {
        "format": "bv*+ba/b",
        "outtmpl": str(work_dir / "source.%(ext)s"),
        "merge_output_format": "mp4",
        "noplaylist": True,
        "quiet": True,
        "no_warnings": True,
        "retries": 3,
        "fragment_retries": 3,
        "progress_hooks": [progress_hook],
    }
    with yt_dlp.YoutubeDL(options) as ydl:
        info = ydl.extract_info(job["source_video_url"], download=True)

    candidates = sorted(
        [
            path
            for path in work_dir.glob("source.*")
            if path.is_file() and path.suffix.lower() in {".mp4", ".mov", ".mkv", ".webm"}
        ],
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )
    if not candidates:
        raise RuntimeError("Source downloader did not create a video file")

    raw_content = (
        job.get("raw_content")
        or (info or {}).get("description")
        or (info or {}).get("title")
        or ""
    )
    cleaned = clean_post_content(raw_content)
    clean_content = (
        cleaned["clean_content"]
        if action.get("content_cleaner_enabled")
        else cleaned["raw_content"].strip()
    )
    source_path = candidates[0].resolve()
    _update_job_runtime(
        job["id"],
        source_local_path=str(source_path),
        raw_content=cleaned["raw_content"],
        clean_content=clean_content,
        removed_links=json.dumps(cleaned["removed_links"], ensure_ascii=False),
        removed_lines=json.dumps(cleaned["removed_lines"], ensure_ascii=False),
        stage="downloaded",
        progress=35,
    )
    return source_path


def _prepare_job(job_id):
    try:
        job = get_job(job_id)
        action = get_action(job["action_id"])
        source_path = _download_job_source(job, action)
        output_dir = _job_work_dir(job_id) / "prepared"
        output_dir.mkdir(parents=True, exist_ok=True)
        last_reported = -1

        def render_progress(payload):
            nonlocal last_reported
            raw_progress = float((payload or {}).get("progress") or 0)
            percent = 35 + int(max(0.0, min(1.0, raw_progress)) * 60)
            if percent != last_reported:
                last_reported = percent
                _update_job_runtime(
                    job_id,
                    stage=str((payload or {}).get("stage") or "render"),
                    progress=percent,
                )

        result = render_action_video(
            action["id"],
            str(source_path),
            output_dir=str(output_dir),
            progress_callback=render_progress,
        )
        if result.get("status") != "ok":
            raise RuntimeError(
                result.get("error")
                or result.get("message")
                or "Shared video pipeline returned an error"
            )
        output_path = Path(str(result.get("output_path") or "")).resolve()
        if not output_path.is_file():
            raise RuntimeError("Shared video pipeline did not create an output file")

        _update_job_runtime(
            job_id,
            status="ready",
            stage="ready",
            progress=95,
            output_path=str(output_path),
            scheduled_at=None,
            error="",
        )
    except Exception as error:
        _update_job_runtime(
            job_id,
            status="error",
            stage="prepare_error",
            error=str(error),
        )
        try:
            job = get_job(job_id)
            if job.get("action_id"):
                with _connect() as conn:
                    conn.execute(
                        """
                        UPDATE reup_actions
                        SET progress_errors = progress_errors + 1,
                            updated_at = ?
                        WHERE id = ?
                        """,
                        (_now(), job["action_id"]),
                    )
                    conn.commit()
        except Exception:
            pass
    finally:
        with _PREPARE_LOCK:
            _PREPARE_JOBS_RUNNING.discard(job_id)


def _dispatch_prepare_jobs():
    while True:
        with _PREPARE_LOCK:
            available = AUTO_REUP_PREPARE_WORKERS - len(_PREPARE_JOBS_RUNNING)
        if available <= 0:
            return
        job_id = _claim_next_queued_job()
        if not job_id:
            return
        with _PREPARE_LOCK:
            _PREPARE_JOBS_RUNNING.add(job_id)
        threading.Thread(
            target=_prepare_job,
            args=(job_id,),
            name=f"auto-reup-prepare-{job_id[:8]}",
            daemon=True,
        ).start()


def _fill_enabled_action_queues():
    for action in list_actions():
        if not action.get("enabled"):
            continue
        try:
            fill_action_queue_from_inventory(action["id"])
        except Exception:
            pass


def _parse_clock(value, fallback):
    try:
        hour, minute = [int(part) for part in str(value or "").split(":", 1)]
        return max(0, min(23, hour)), max(0, min(59, minute))
    except (TypeError, ValueError):
        return fallback


def _active_window(action, reference):
    start_hour, start_minute = _parse_clock(action.get("active_from"), (9, 0))
    end_hour, end_minute = _parse_clock(action.get("active_to"), (22, 30))
    start = reference.replace(
        hour=start_hour,
        minute=start_minute,
        second=0,
        microsecond=0,
    )
    end = reference.replace(
        hour=end_hour,
        minute=end_minute,
        second=0,
        microsecond=0,
    )
    if end <= start:
        if reference < end:
            start -= timedelta(days=1)
        else:
            end += timedelta(days=1)
    return start, end


def _clamp_to_active_window(action, candidate):
    start, end = _active_window(action, candidate)
    if candidate < start:
        return start
    if candidate <= end:
        return candidate
    next_reference = candidate + timedelta(days=1)
    next_start, _ = _active_window(action, next_reference)
    return next_start


def _window_start_for_date(action, target_date):
    start_hour, start_minute = _parse_clock(action.get("active_from"), (9, 0))
    return datetime(
        target_date.year,
        target_date.month,
        target_date.day,
        start_hour,
        start_minute,
        tzinfo=AUTO_REUP_TIMEZONE,
    )


def _posted_today(action_id, now_local):
    with _connect() as conn:
        rows = conn.execute(
            """
            SELECT posted_at
            FROM reup_jobs
            WHERE action_id = ? AND status = 'posted' AND posted_at IS NOT NULL
            """,
            (action_id,),
        ).fetchall()
    total = 0
    for row in rows:
        posted_at = _parse_iso(row["posted_at"])
        if posted_at and posted_at.astimezone(AUTO_REUP_TIMEZONE).date() == now_local.date():
            total += 1
    return total


def _manual_daily_slots(action, target_date):
    start_minutes = _clock_to_minutes(action.get("active_from") or "00:00")
    end_minutes = _clock_to_minutes(action.get("active_to") or "23:59")
    crosses_midnight = end_minutes <= start_minutes
    slots = []
    for clock in action.get("manual_times") or []:
        minutes = _clock_to_minutes(clock)
        slot_date = target_date + timedelta(days=1) if crosses_midnight and minutes < start_minutes else target_date
        slots.append(
            datetime(
                slot_date.year,
                slot_date.month,
                slot_date.day,
                minutes // 60,
                minutes % 60,
                tzinfo=AUTO_REUP_TIMEZONE,
            )
        )
    return sorted(slots)


def _golden_window_centers(action, start, end):
    profile = _normalize_smart_profile(action.get("smart_profile"))
    windows = US_GOLDEN_WINDOWS if profile == "us" else VN_GOLDEN_WINDOWS
    centers = []
    for day_offset in range(2):
        day = start.date() + timedelta(days=day_offset)
        for window_start, window_end in windows:
            candidate_start = datetime(
                day.year,
                day.month,
                day.day,
                window_start // 60,
                window_start % 60,
                tzinfo=AUTO_REUP_TIMEZONE,
            )
            candidate_end = datetime(
                day.year,
                day.month,
                day.day,
                window_end // 60,
                window_end % 60,
                tzinfo=AUTO_REUP_TIMEZONE,
            )
            overlap_start = max(start, candidate_start)
            overlap_end = min(end, candidate_end)
            if overlap_end > overlap_start:
                centers.append(overlap_start + (overlap_end - overlap_start) / 2)
    return centers


def _smart_daily_slots(action, target_date):
    daily_limit = max(1, int(action.get("daily_limit") or 1))
    start = _window_start_for_date(action, target_date)
    start, end = _active_window(action, start)
    span_minutes = max(1, int((end - start).total_seconds() // 60))
    centers = _golden_window_centers(action, start, end)
    jitter = max(0, min(45, int(action.get("jitter_minutes") or 0)))
    slots = []

    for index in range(daily_limit):
        base = start + timedelta(minutes=round(((index + 0.5) * span_minutes) / daily_limit))
        if centers:
            nearest = min(centers, key=lambda item: abs((item - base).total_seconds()))
            blended_minutes = int((nearest - base).total_seconds() // 60 * 0.55)
            base = base + timedelta(minutes=blended_minutes)
        if jitter:
            base = base + timedelta(minutes=_SCHEDULE_RANDOM.randint(-jitter, jitter))
        slots.append(min(max(base, start), end))

    slots.sort()
    min_spacing = min(90, max(10, span_minutes // max(daily_limit * 2, 1)))
    normalized = []
    for slot in slots:
        if normalized and slot < normalized[-1] + timedelta(minutes=min_spacing):
            slot = normalized[-1] + timedelta(minutes=min_spacing)
        normalized.append(min(slot, end))
    return normalized


def _daily_schedule_slots(action, target_date):
    mode = _normalize_schedule_mode(action.get("schedule_mode"))
    if mode == "manual_times":
        slots = _manual_daily_slots(action, target_date)
        if slots:
            return slots
    if mode == "smart_daily":
        return _smart_daily_slots(action, target_date)
    return []


def _schedule_candidate_for_slot(action, slot_index, target_date, now_local, previous=None):
    mode = _normalize_schedule_mode(action.get("schedule_mode"))
    if mode == "random_interval":
        if previous:
            candidate = previous + timedelta(minutes=choose_action_gap_minutes(action["id"]))
        else:
            candidate = now_local if target_date == now_local.date() else _window_start_for_date(action, target_date)
        return _clamp_to_active_window(action, candidate)

    slots = _daily_schedule_slots(action, target_date)
    if not slots:
        return _clamp_to_active_window(action, now_local)
    candidate = slots[min(slot_index, len(slots) - 1)]
    if target_date == now_local.date() and candidate < now_local:
        candidate = now_local
    if previous and candidate <= previous:
        candidate = previous + timedelta(minutes=5)
    return candidate


def _schedule_ready_jobs():
    now_utc = datetime.now(timezone.utc)
    now_local = now_utc.astimezone(AUTO_REUP_TIMEZONE)
    with _connect() as conn:
        rows = conn.execute(
            """
            SELECT j.id, j.action_id, j.scheduled_at
            FROM reup_jobs j
            JOIN reup_actions a ON a.id = j.action_id
            WHERE j.status = 'ready' AND a.enabled = 1
            ORDER BY j.created_at ASC
            """
        ).fetchall()

    action_next = {}
    action_scheduled_today = {}
    for row in rows:
        scheduled_at = _parse_iso(row["scheduled_at"])
        if not scheduled_at:
            continue
        scheduled_local = scheduled_at.astimezone(AUTO_REUP_TIMEZONE)
        if scheduled_local.date() == now_local.date():
            action_scheduled_today[row["action_id"]] = (
                action_scheduled_today.get(row["action_id"], 0) + 1
            )
        current = action_next.get(row["action_id"])
        if current is None or scheduled_local > current:
            action_next[row["action_id"]] = scheduled_local

    for row in rows:
        if row["scheduled_at"]:
            continue
        action = get_action(row["action_id"])
        daily_limit = max(1, int(action["daily_limit"] or 1))
        committed_today = (
            _posted_today(action["id"], now_local)
            + action_scheduled_today.get(action["id"], 0)
        )
        if committed_today >= daily_limit:
            target_date = now_local.date() + timedelta(days=1)
            candidate = _schedule_candidate_for_slot(
                action,
                0,
                target_date,
                now_local,
                previous=action_next.get(action["id"]),
            )
        else:
            previous = action_next.get(action["id"])
            target_date = now_local.date()
            candidate = _schedule_candidate_for_slot(
                action,
                committed_today,
                target_date,
                now_local,
                previous=previous,
            )
        _update_job_runtime(row["id"], scheduled_at=candidate.astimezone(timezone.utc).isoformat(timespec="seconds"))
        action_next[action["id"]] = candidate
        if candidate.date() == now_local.date():
            action_scheduled_today[action["id"]] = (
                action_scheduled_today.get(action["id"], 0) + 1
            )


def _page_publish_credentials(fanpage_id):
    with _connect() as conn:
        row = conn.execute(
            """
            SELECT page.id, page.page_id, page.name, page.page_token_status,
                   page.access_status, page.is_enabled, page.page_access_token,
                   token.graph_version,
                   link.encrypted_page_token
            FROM fanpages page
            LEFT JOIN meta_user_tokens token ON token.id = page.credential_id
            LEFT JOIN meta_token_page_links link
              ON link.fanpage_id = page.id
             AND link.token_id = page.credential_id
            WHERE page.id = ?
            LIMIT 1
            """,
            (fanpage_id,),
        ).fetchone()
    if not row:
        raise ValueError("Destination Page no longer exists")
    if not row["is_enabled"] or row["page_token_status"] != "valid":
        raise ValueError("Destination Page token is not ready")
    page_token = ""
    if row["encrypted_page_token"]:
        page_token = _decrypt_secret(row["encrypted_page_token"])
    if not page_token:
        page_token = str(row["page_access_token"] or "").strip()
    if not page_token:
        raise ValueError("Destination Page has no access token")
    return {
        "page_id": row["page_id"],
        "page_name": row["name"],
        "page_token": page_token,
        "graph_version": row["graph_version"] or GRAPH_API_VERSION,
    }


def _publish_job(job_id):
    try:
        job = get_job(job_id)
        credentials = _page_publish_credentials(job["target_page_id"])
        with _connect() as conn:
            if _target_source_posted(
                conn,
                job["target_page_id"],
                job["source_post_id"],
                job["source_video_url"],
            ):
                _update_job_runtime(
                    job_id,
                    status="skipped_duplicate",
                    stage="skipped_duplicate",
                    progress=100,
                    error="Source video was already posted to this destination Page",
                )
                _record_action_event(
                    job.get("action_id"),
                    "job_skipped_duplicate",
                    "Bo qua job vi video nguon da tung dang len Page dich.",
                    job_id=job_id,
                    payload={
                        "source_post_id": job.get("source_post_id") or "",
                        "target_page_id": job.get("target_page_id") or "",
                    },
                )
                return
        output_path = Path(str(job.get("output_path") or "")).resolve()
        if not output_path.is_file():
            raise FileNotFoundError("Prepared video is missing")

        _update_job_runtime(job_id, stage="publishing", progress=98)
        endpoint = (
            f"https://graph.facebook.com/{credentials['graph_version']}/"
            f"{credentials['page_id']}/videos"
        )
        with output_path.open("rb") as video_file:
            response = requests.post(
                endpoint,
                data={
                    "access_token": credentials["page_token"],
                    "description": job.get("clean_content") or "",
                    "published": "true",
                },
                files={
                    "source": (
                        output_path.name,
                        video_file,
                        "video/mp4",
                    )
                },
                timeout=(30, 1800),
            )
        try:
            payload = response.json()
        except ValueError:
            payload = {}
        if not response.ok or payload.get("error"):
            graph_error = payload.get("error") or {}
            message = graph_error.get("message") or response.text or "Meta video upload failed"
            raise RuntimeError(f"Meta API: {message}")
        publish_id = str(payload.get("id") or "")
        posted_at = _now()
        _update_job_runtime(
            job_id,
            status="posted",
            stage="posted",
            progress=100,
            publish_id=publish_id,
            posted_at=posted_at,
            error="",
        )
        if job.get("action_id"):
            with _connect() as conn:
                action = get_action(job["action_id"])
                source_key = _source_key_for_action(action)
                source_hash = _source_hash(job["source_post_id"], job["source_video_url"])
                conn.execute(
                    """
                    INSERT OR IGNORE INTO posted_source_history (
                        id, target_page_id, source_key, platform, source_post_id,
                        source_video_url, source_hash, action_id, job_id, publish_id,
                        posted_at, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        _new_id(),
                        job["target_page_id"],
                        source_key,
                        str(action.get("platform") or "facebook").strip().lower(),
                        job["source_post_id"] or "",
                        job["source_video_url"] or "",
                        source_hash,
                        job["action_id"],
                        job_id,
                        publish_id,
                        posted_at,
                        posted_at,
                    ),
                )
                conn.execute(
                    """
                    UPDATE reup_actions
                    SET progress_posted = progress_posted + 1,
                        updated_at = ?
                    WHERE id = ?
                    """,
                    (posted_at, job["action_id"]),
                )
                conn.commit()
        shutil.rmtree(_job_work_dir(job_id), ignore_errors=True)
    except Exception as error:
        _update_job_runtime(
            job_id,
            status="error",
            stage="publish_error",
            error=str(error),
        )
        try:
            job = get_job(job_id)
            if job.get("action_id"):
                with _connect() as conn:
                    conn.execute(
                        """
                        UPDATE reup_actions
                        SET progress_errors = progress_errors + 1,
                            updated_at = ?
                        WHERE id = ?
                        """,
                        (_now(), job["action_id"]),
                    )
                    conn.commit()
        except Exception:
            pass
    finally:
        _PUBLISH_LOCK.release()


def _dispatch_due_publish():
    if not _PUBLISH_LOCK.acquire(blocking=False):
        return
    now = _now()
    with _connect() as conn:
        row = conn.execute(
            """
            SELECT j.id, j.action_id
            FROM reup_jobs j
            JOIN reup_actions a ON a.id = j.action_id
            JOIN fanpages p ON p.id = j.target_page_id
            WHERE j.status = 'ready'
              AND j.scheduled_at IS NOT NULL
              AND j.scheduled_at <= ?
              AND a.enabled = 1
              AND p.is_enabled = 1
              AND p.page_token_status = 'valid'
            ORDER BY j.scheduled_at ASC, j.created_at ASC
            LIMIT 1
            """,
            (now,),
        ).fetchone()
    if not row:
        _PUBLISH_LOCK.release()
        return

    action = get_action(row["action_id"])
    now_local = datetime.now(timezone.utc).astimezone(AUTO_REUP_TIMEZONE)
    active_start, active_end = _active_window(action, now_local)
    daily_limit = max(1, int(action.get("daily_limit") or 1))
    if (
        not (active_start <= now_local <= active_end)
        or _posted_today(action["id"], now_local) >= daily_limit
    ):
        _PUBLISH_LOCK.release()
        _update_job_runtime(row["id"], scheduled_at=None)
        return

    with _connect() as conn:
        conn.execute("BEGIN IMMEDIATE")
        claimed = conn.execute(
            """
            UPDATE reup_jobs
            SET status = 'publishing',
                stage = 'publishing',
                progress = 97,
                error = '',
                updated_at = ?
            WHERE id = ? AND status = 'ready'
            """,
            (now, row["id"]),
        ).rowcount
        conn.commit()
    if not claimed:
        _PUBLISH_LOCK.release()
        return
    threading.Thread(
        target=_publish_job,
        args=(row["id"],),
        name=f"auto-reup-publish-{row['id'][:8]}",
        daemon=True,
    ).start()


def _runtime_loop():
    while not _RUNTIME_STOP.wait(AUTO_REUP_RUNTIME_INTERVAL_SECONDS):
        try:
            refresh_due_page_insights()
            _fill_enabled_action_queues()
            _dispatch_prepare_jobs()
            _schedule_ready_jobs()
            _dispatch_due_publish()
        except Exception:
            time.sleep(1)


def start_auto_reup_runtime_monitor():
    global _RUNTIME_THREAD
    init_auto_reup_db()
    AUTO_REUP_JOB_DIR.mkdir(parents=True, exist_ok=True)
    if _RUNTIME_THREAD and _RUNTIME_THREAD.is_alive():
        return
    _RUNTIME_STOP.clear()
    _RUNTIME_THREAD = threading.Thread(
        target=_runtime_loop,
        name="auto-reup-runtime-monitor",
        daemon=True,
    )
    _RUNTIME_THREAD.start()


def stop_auto_reup_runtime_monitor():
    _RUNTIME_STOP.set()


def _source_item_id(video_url):
    parsed = urlparse(str(video_url or "").strip())
    parts = [part for part in parsed.path.split("/") if part]
    for marker in ("reel", "videos", "video"):
        if marker in parts:
            index = parts.index(marker)
            if index + 1 < len(parts):
                return parts[index + 1]
    if parts:
        return parts[-1]
    return hashlib.sha256(str(video_url).encode("utf-8")).hexdigest()[:24]


def _normalize_source_url(value):
    url = str(value or "").strip()
    if not url:
        return ""
    return url.split("?", 1)[0].rstrip("/")


def _source_key_for_action(action):
    platform = str(action.get("platform") or "facebook").strip().lower()
    source_url = _normalize_source_url(action.get("source_url"))
    return f"{platform}:{source_url.casefold()}"


def _source_hash(source_post_id, source_video_url):
    source_id = str(source_post_id or "").strip()
    video_url = _normalize_source_url(source_video_url)
    raw = source_id or video_url
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _source_known_for_action(action):
    source_key = _source_key_for_action(action)
    with _connect() as conn:
        rows = conn.execute(
            """
            SELECT source_post_id
            FROM source_video_inventory
            WHERE source_key = ?
            """,
            (source_key,),
        ).fetchall()
    return {row["source_post_id"] for row in rows}


def _reup_target_total_for_action(conn, action):
    source_key = _source_key_for_action(action)
    inventory_total = conn.execute(
        """
        SELECT COUNT(*) AS total
        FROM source_video_inventory
        WHERE source_key = ?
        """,
        (source_key,),
    ).fetchone()["total"]
    job_total = conn.execute(
        """
        SELECT COUNT(*) AS total
        FROM reup_jobs
        WHERE action_id = ?
        """,
        (action["id"],),
    ).fetchone()["total"]
    return int(max(inventory_total or 0, job_total or 0, action.get("progress_total") or 0))


def _target_source_posted(conn, target_page_id, source_post_id, source_video_url):
    row = conn.execute(
        """
        SELECT id
        FROM posted_source_history
        WHERE target_page_id = ?
          AND source_hash = ?
        LIMIT 1
        """,
        (
            target_page_id,
            _source_hash(source_post_id, source_video_url),
        ),
    ).fetchone()
    return bool(row)


def _upsert_source_inventory(conn, action, item, now):
    source_post_id = str(item.get("source_post_id") or "").strip()
    source_video_url = _normalize_source_url(item.get("source_video_url"))
    if not source_post_id or not source_video_url:
        return False

    cleaned = clean_post_content(item.get("raw_content") or "")
    source_key = _source_key_for_action(action)
    existing = conn.execute(
        """
        SELECT id
        FROM source_video_inventory
        WHERE source_key = ? AND source_post_id = ?
        LIMIT 1
        """,
        (source_key, source_post_id),
    ).fetchone()
    data = {
        "id": _new_id(),
        "source_key": source_key,
        "platform": str(action.get("platform") or "facebook").strip().lower(),
        "source_url": _normalize_source_url(action.get("source_url")),
        "source_post_id": source_post_id,
        "source_video_url": source_video_url,
        "raw_content": cleaned["raw_content"],
        "clean_content": cleaned["clean_content"],
        "removed_links": json.dumps(cleaned["removed_links"], ensure_ascii=False),
        "removed_lines": json.dumps(cleaned["removed_lines"], ensure_ascii=False),
        "source_published_at": item.get("source_published_at") or None,
        "first_seen_at": now,
        "last_seen_at": now,
        "created_at": now,
        "updated_at": now,
    }
    conn.execute(
        """
        INSERT INTO source_video_inventory (
            id, source_key, platform, source_url, source_post_id,
            source_video_url, raw_content, clean_content, removed_links,
            removed_lines, source_published_at, first_seen_at, last_seen_at,
            created_at, updated_at
        ) VALUES (
            :id, :source_key, :platform, :source_url, :source_post_id,
            :source_video_url, :raw_content, :clean_content, :removed_links,
            :removed_lines, :source_published_at, :first_seen_at, :last_seen_at,
            :created_at, :updated_at
        )
        ON CONFLICT(source_key, source_post_id) DO UPDATE SET
            source_video_url = excluded.source_video_url,
            raw_content = CASE
                WHEN COALESCE(excluded.raw_content, '') != '' THEN excluded.raw_content
                ELSE source_video_inventory.raw_content
            END,
            clean_content = CASE
                WHEN COALESCE(excluded.clean_content, '') != '' THEN excluded.clean_content
                ELSE source_video_inventory.clean_content
            END,
            removed_links = CASE
                WHEN COALESCE(excluded.removed_links, '') != '' THEN excluded.removed_links
                ELSE source_video_inventory.removed_links
            END,
            removed_lines = CASE
                WHEN COALESCE(excluded.removed_lines, '') != '' THEN excluded.removed_lines
                ELSE source_video_inventory.removed_lines
            END,
            source_published_at = COALESCE(excluded.source_published_at, source_video_inventory.source_published_at),
            last_seen_at = excluded.last_seen_at,
            updated_at = excluded.updated_at
        """,
        data,
    )
    return existing is None


def _action_active_job_count(conn, action_id):
    return conn.execute(
        """
        SELECT COUNT(*) AS total
        FROM reup_jobs
        WHERE action_id = ?
          AND status IN ('queued', 'processing', 'ready', 'publishing')
        """,
        (action_id,),
    ).fetchone()["total"]


def _create_job_from_inventory(conn, action, inventory_row, now):
    target_page_id = action.get("target_page_id") or None
    if not target_page_id:
        return False
    if _target_source_posted(
        conn,
        target_page_id,
        inventory_row["source_post_id"],
        inventory_row["source_video_url"],
    ):
        return False

    exists = conn.execute(
        """
        SELECT id
        FROM reup_jobs
        WHERE action_id = ?
          AND (
            source_post_id = ?
            OR source_video_url = ?
          )
        LIMIT 1
        """,
        (
            action["id"],
            inventory_row["source_post_id"],
            inventory_row["source_video_url"],
        ),
    ).fetchone()
    if exists:
        return False

    conn.execute(
        """
        INSERT INTO reup_jobs (
            id, action_id, source_id, target_page_id,
            source_post_id, source_video_url, raw_content,
            clean_content, removed_links, removed_lines, status,
            scheduled_at, posted_at, error, created_at, updated_at
        ) VALUES (
            ?, ?, NULL, ?, ?, ?, ?, ?, ?, ?, 'queued',
            NULL, NULL, '', ?, ?
        )
        """,
        (
            _new_id(),
            action["id"],
            target_page_id,
            inventory_row["source_post_id"],
            inventory_row["source_video_url"],
            inventory_row["raw_content"] or "",
            inventory_row["clean_content"] or "",
            inventory_row["removed_links"] or "[]",
            inventory_row["removed_lines"] or "[]",
            now,
            now,
        ),
    )
    return True


def fill_action_queue_from_inventory(action_id):
    action = get_action(action_id)
    if not action.get("enabled"):
        return {"created": 0, "needed": 0}
    queue_target = max(1, int(action.get("daily_limit") or 1)) * ACTION_QUEUE_BUFFER_DAYS
    now = _now()
    created = 0
    with _connect() as conn:
        active_count = _action_active_job_count(conn, action_id)
        needed = max(0, queue_target - active_count)
        if needed <= 0:
            return {"created": 0, "needed": 0}
        rows = conn.execute(
            """
            SELECT *
            FROM source_video_inventory
            WHERE source_key = ?
            ORDER BY
                COALESCE(source_published_at, first_seen_at) DESC,
                first_seen_at DESC
            LIMIT ?
            """,
            (_source_key_for_action(action), max(needed * 6, 30)),
        ).fetchall()
        for row in rows:
            if created >= needed:
                break
            if _create_job_from_inventory(conn, action, row, now):
                created += 1
        conn.commit()
    return {"created": created, "needed": needed}


def _discover_action_source(action):
    platform = str(action.get("platform") or "facebook").strip().lower()
    source_url = str(action.get("source_url") or "").strip()
    if not source_url:
        raise ValueError("Action source URL is empty")

    if platform == "facebook":
        from core.crawler.fb_scraper import get_facebook_reels

        known_ids = _source_known_for_action(action)
        initial_scan = not known_ids
        with _FACEBOOK_SCAN_LOCK:
            result = get_facebook_reels(
                source_url,
                interactive_login=False,
                max_items=SOURCE_SCAN_INITIAL_LIMIT if initial_scan else SOURCE_SCAN_INCREMENTAL_LIMIT,
                stop_after_known=0 if initial_scan else SOURCE_SCAN_STOP_KNOWN,
                known_item_ids=known_ids,
                hidden=True,
            )
        return [
            {
                "source_post_id": _source_item_id(video_url),
                "source_video_url": video_url,
                "raw_content": "",
            }
            for video_url in result.get("reels_urls", [])
        ]

    if platform == "tiktok":
        import yt_dlp

        options = {
            "extract_flat": True,
            "quiet": True,
            "no_warnings": True,
            "ignoreerrors": True,
            "playlistreverse": True,
        }
        with yt_dlp.YoutubeDL(options) as ydl:
            info = ydl.extract_info(source_url, download=False)
        if not info:
            return []
        entries = info.get("entries") or [info]
        items = []
        for entry in entries:
            if not entry:
                continue
            video_url = entry.get("webpage_url") or entry.get("url")
            if not video_url:
                continue
            items.append(
                {
                    "source_post_id": str(entry.get("id") or _source_item_id(video_url)),
                    "source_video_url": video_url,
                    "raw_content": entry.get("description") or entry.get("title") or "",
                }
            )
        return items

    raise ValueError(f"Automatic source scan does not support platform: {platform}")


def _action_scan_due(action):
    last_scan = _parse_iso(action.get("last_scan_at"))
    if not last_scan:
        return True
    interval = max(5, int(action.get("scan_interval_minutes") or 60))
    return datetime.now(timezone.utc) >= last_scan + timedelta(minutes=interval)


def _set_action_scan_state(action_id, status, error=None):
    with _connect() as conn:
        conn.execute(
            """
            UPDATE reup_actions
            SET scan_status = ?,
                last_scan_error = ?,
                updated_at = ?
            WHERE id = ?
            """,
            (status, error or "", _now(), action_id),
        )
        conn.commit()
    messages = {
        "scanning": "Dang quet nguon de tim video moi.",
        "ready": "Quet nguon hoan tat.",
        "error": "Quet nguon that bai.",
        "idle": "Dang cho lan quet tiep theo.",
    }
    _record_action_event(
        action_id,
        f"scan_{status}",
        messages.get(status, f"Trang thai quet: {status}."),
        level="error" if status == "error" else "info",
        payload={"error": error or ""},
    )


def scan_action_source(action_id, force=False):
    action = get_action(action_id)
    if not action.get("enabled") and not force:
        return {"action_id": action_id, "status": "disabled", "created": 0}
    if not force and not _action_scan_due(action):
        return {"action_id": action_id, "status": "not_due", "created": 0}

    _set_action_scan_state(action_id, "scanning")
    try:
        discovered = _discover_action_source(action)
        unique_items = {}
        for item in discovered:
            source_post_id = str(item.get("source_post_id") or "").strip()
            source_video_url = str(item.get("source_video_url") or "").strip()
            if not source_post_id or not source_video_url:
                continue
            unique_items[source_post_id] = {
                **item,
                "source_post_id": source_post_id,
                "source_video_url": source_video_url,
            }

        added_inventory = 0
        touched_inventory = 0
        now = _now()
        with _connect() as conn:
            for item in unique_items.values():
                if _upsert_source_inventory(conn, action, item, now):
                    added_inventory += 1
                touched_inventory += 1

            conn.execute(
                """
                UPDATE reup_actions
                SET progress_total = ?,
                    progress_scanned = ?,
                    last_scan_at = ?,
                    scan_status = 'ready',
                    last_scan_error = '',
                    updated_at = ?
                WHERE id = ?
                """,
                (len(unique_items), len(unique_items), now, now, action_id),
            )
            conn.commit()
        queue = fill_action_queue_from_inventory(action_id)

        _record_action_event(
            action_id,
            "scan_completed",
            (
                f"Quet xong {len(unique_items)} video, "
                f"them vao kho {added_inventory}, tao job {queue['created']}."
            ),
            payload={
                "total": len(unique_items),
                "inventory_added": added_inventory,
                "inventory_seen": touched_inventory,
                "jobs_created": queue["created"],
            },
        )
        return {
            "action_id": action_id,
            "status": "ready",
            "total": len(unique_items),
            "inventory_added": added_inventory,
            "jobs_created": queue["created"],
        }
    except Exception as error:
        now = _now()
        message = str(error)
        lowered = message.lower()
        login_required = any(
            marker in lowered
            for marker in [
                "facebook_login_required",
                "facebook_checkpoint_required",
                "not logged in",
                "login required",
                "checkpoint",
            ]
        )
        with _connect() as conn:
            conn.execute(
                """
                UPDATE reup_actions
                SET scan_status = ?,
                    last_scan_error = ?,
                    progress_errors = progress_errors + 1,
                    last_scan_at = ?,
                    updated_at = ?
                WHERE id = ?
                """,
                ("login_required" if login_required else "error", message, now, now, action_id),
            )
            conn.commit()
        _record_action_event(
            action_id,
            "scan_login_required" if login_required else "scan_error",
            (
                "Facebook session can dang nhap lai truoc khi quet nguon."
                if login_required
                else f"Quet nguon that bai: {error}"
            ),
            level="error",
            payload={"error": message},
        )
        raise


def _scan_action_worker(action_id, force):
    try:
        scan_action_source(action_id, force=force)
    finally:
        with _ACTION_SCAN_LOCK:
            _ACTION_SCANS_RUNNING.discard(action_id)


def request_action_scan(action_id, force=True):
    action = get_action(action_id)
    if not force and not _action_scan_due(action):
        return {"action_id": action_id, "started": False, "reason": "not_due"}

    with _ACTION_SCAN_LOCK:
        if action_id in _ACTION_SCANS_RUNNING:
            return {"action_id": action_id, "started": False, "reason": "already_running"}
        _ACTION_SCANS_RUNNING.add(action_id)

    thread = threading.Thread(
        target=_scan_action_worker,
        args=(action_id, force),
        name=f"auto-reup-scan-{action_id[:8]}",
        daemon=True,
    )
    thread.start()
    return {"action_id": action_id, "started": True}


def open_facebook_login_session():
    from core.crawler.fb_scraper import open_facebook_login_browser

    return open_facebook_login_browser()


def _action_monitor_loop():
    while not _ACTION_MONITOR_STOP.wait(10):
        try:
            for action in list_actions():
                if not action.get("enabled"):
                    continue
                request_action_scan(action["id"], force=False)
        except Exception:
            time.sleep(2)


def start_auto_reup_action_monitor():
    global _ACTION_MONITOR_THREAD
    init_auto_reup_db()
    if _ACTION_MONITOR_THREAD and _ACTION_MONITOR_THREAD.is_alive():
        return
    _ACTION_MONITOR_STOP.clear()
    _ACTION_MONITOR_THREAD = threading.Thread(
        target=_action_monitor_loop,
        name="auto-reup-action-monitor",
        daemon=True,
    )
    _ACTION_MONITOR_THREAD.start()


def stop_auto_reup_action_monitor():
    _ACTION_MONITOR_STOP.set()


def delete_action(action_id):
    init_auto_reup_db()
    with _connect() as conn:
        conn.execute("DELETE FROM reup_action_events WHERE action_id = ?", (action_id,))
        conn.execute("DELETE FROM reup_jobs WHERE action_id = ?", (action_id,))
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
                SELECT j.*, COALESCE(s.name, a.name) AS source_name,
                       p.name AS target_page_name
                FROM reup_jobs j
                LEFT JOIN reup_sources s ON s.id = j.source_id
                LEFT JOIN reup_actions a ON a.id = j.action_id
                LEFT JOIN fanpages p ON p.id = j.target_page_id
                WHERE j.status = ?
                ORDER BY
                    CASE j.status
                        WHEN 'processing' THEN 0
                        WHEN 'publishing' THEN 1
                        WHEN 'ready' THEN 2
                        WHEN 'queued' THEN 3
                        ELSE 4
                    END,
                    j.created_at DESC
                LIMIT ?
                """,
                (status, safe_limit),
            ).fetchall()
        else:
            rows = conn.execute(
                """
                SELECT j.*, COALESCE(s.name, a.name) AS source_name,
                       p.name AS target_page_name
                FROM reup_jobs j
                LEFT JOIN reup_sources s ON s.id = j.source_id
                LEFT JOIN reup_actions a ON a.id = j.action_id
                LEFT JOIN fanpages p ON p.id = j.target_page_id
                ORDER BY
                    CASE j.status
                        WHEN 'processing' THEN 0
                        WHEN 'publishing' THEN 1
                        WHEN 'ready' THEN 2
                        WHEN 'queued' THEN 3
                        ELSE 4
                    END,
                    j.created_at DESC
                LIMIT ?
                """,
                (safe_limit,),
            ).fetchall()

    return [_row_to_dict(row) for row in rows]


def get_action_runtime(action_id, job_limit=80, event_limit=160):
    init_auto_reup_db()
    action = get_action(action_id)
    safe_job_limit = max(1, min(200, int(job_limit or 80)))
    safe_event_limit = max(1, min(500, int(event_limit or 160)))
    with _connect() as conn:
        job_rows = conn.execute(
            """
            SELECT j.*, COALESCE(s.name, a.name) AS source_name,
                   p.name AS target_page_name
            FROM reup_jobs j
            LEFT JOIN reup_sources s ON s.id = j.source_id
            LEFT JOIN reup_actions a ON a.id = j.action_id
            LEFT JOIN fanpages p ON p.id = j.target_page_id
            WHERE j.action_id = ?
            ORDER BY
                CASE j.status
                    WHEN 'processing' THEN 0
                    WHEN 'publishing' THEN 1
                    WHEN 'ready' THEN 2
                    WHEN 'queued' THEN 3
                    WHEN 'error' THEN 4
                    ELSE 5
                END,
                COALESCE(j.scheduled_at, j.updated_at) ASC,
                j.created_at DESC
            LIMIT ?
            """,
            (action_id, safe_job_limit),
        ).fetchall()
        event_rows = conn.execute(
            """
            SELECT id, action_id, job_id, level, event_type, message,
                   payload, created_at
            FROM reup_action_events
            WHERE action_id = ?
            ORDER BY id DESC
            LIMIT ?
            """,
            (action_id, safe_event_limit),
        ).fetchall()

    jobs = [_row_to_dict(row) for row in job_rows]
    events = []
    for row in event_rows:
        item = dict(row)
        item["payload"] = _decode_json(item.get("payload"), {})
        events.append(item)

    now_utc = datetime.now(timezone.utc)
    last_scan_at = _parse_iso(action.get("last_scan_at"))
    scan_interval = max(5, int(action.get("scan_interval_minutes") or 60))
    next_scan_at = (
        (last_scan_at + timedelta(minutes=scan_interval))
        if last_scan_at
        else now_utc
    )
    scheduled_jobs = [
        job for job in jobs
        if job.get("status") == "ready" and _parse_iso(job.get("scheduled_at"))
    ]
    next_publish_job = min(
        scheduled_jobs,
        key=lambda item: _parse_iso(item.get("scheduled_at")),
        default=None,
    )

    active_job = next(
        (
            job for job in jobs
            if job.get("status") in {"processing", "publishing"}
        ),
        None,
    )
    if not action.get("enabled"):
        runtime_phase = "paused"
    elif action.get("scan_status") == "scanning":
        runtime_phase = "scanning"
    elif active_job:
        runtime_phase = active_job.get("stage") or active_job.get("status")
    elif next_publish_job:
        runtime_phase = "waiting_publish"
    elif any(job.get("status") == "queued" for job in jobs):
        runtime_phase = "queued"
    else:
        runtime_phase = "waiting_scan"

    return {
        "action": action,
        "runtime": {
            "phase": runtime_phase,
            "server_now": now_utc.isoformat(timespec="seconds"),
            "next_scan_at": next_scan_at.isoformat(timespec="seconds"),
            "next_publish_at": (
                next_publish_job.get("scheduled_at")
                if next_publish_job
                else None
            ),
            "next_publish_job_id": (
                next_publish_job.get("id")
                if next_publish_job
                else None
            ),
            "active_job_id": active_job.get("id") if active_job else None,
            "queued": sum(job.get("status") == "queued" for job in jobs),
            "processing": sum(job.get("status") == "processing" for job in jobs),
            "ready": sum(job.get("status") == "ready" for job in jobs),
            "publishing": sum(job.get("status") == "publishing" for job in jobs),
            "posted": sum(job.get("status") == "posted" for job in jobs),
            "errors": sum(job.get("status") == "error" for job in jobs),
        },
        "jobs": jobs,
        "events": events,
    }


def create_job(payload):
    init_auto_reup_db()
    cleaned = clean_post_content(payload.get("raw_content", ""))
    now = _now()
    data = {
        "id": _new_id(),
        "action_id": payload.get("action_id") or None,
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
                id, action_id, source_id, target_page_id, source_post_id, source_video_url,
                raw_content, clean_content, removed_links, removed_lines, status,
                scheduled_at, posted_at, error, created_at, updated_at
            ) VALUES (
                :id, :action_id, :source_id, :target_page_id, :source_post_id, :source_video_url,
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
            SELECT j.*, COALESCE(s.name, a.name) AS source_name,
                   p.name AS target_page_name
            FROM reup_jobs j
            LEFT JOIN reup_sources s ON s.id = j.source_id
            LEFT JOIN reup_actions a ON a.id = j.action_id
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
        "action_id",
        "source_id",
        "target_page_id",
        "source_post_id",
        "source_video_url",
        "raw_content",
        "clean_content",
        "status",
        "stage",
        "progress",
        "source_local_path",
        "output_path",
        "publish_id",
        "attempts",
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
