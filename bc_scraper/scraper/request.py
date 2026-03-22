import atexit
import binascii
import hashlib
import json
import logging
import os
import random
import sqlite3
import threading
import traceback
from time import sleep
from typing import Callable, Dict, Optional

import requests
from requests.adapters import HTTPAdapter


log = logging.getLogger("scraper")


def _is_block_page(resp: str) -> bool:
    return "Verificación de Seguridad" in resp or "challenge-container" in resp


def _looks_like_html(resp: str) -> bool:
    sample = resp[:2048].lower()
    return "<html" in sample or "<!doctype html" in sample or "<table" in sample


CACHE_DB_PATH = ".requestcache.sqlite"

db_lock = threading.Lock()
cache_db: Optional[sqlite3.Connection] = None

session = requests.Session()
adapter = HTTPAdapter(pool_connections=25, pool_maxsize=25)
session.mount("http://", adapter)
session.mount("https://", adapter)

try:
    import cloudscraper

    HAS_CLOUDSCRAPER = True
    scraper = cloudscraper.create_scraper()
    scraper.mount("http://", HTTPAdapter(pool_connections=25, pool_maxsize=25))
    scraper.mount("https://", HTTPAdapter(pool_connections=25, pool_maxsize=25))
except Exception:
    HAS_CLOUDSCRAPER = False
    scraper = None


def _close_cache_db():
    global cache_db
    if cache_db is not None:
        cache_db.close()
        cache_db = None


aexit_registered = False


def _ensure_cache_db() -> Optional[sqlite3.Connection]:
    global cache_db
    global aexit_registered

    if cache_db is not None:
        return cache_db

    with db_lock:
        if cache_db is None:
            cache_db = sqlite3.connect(CACHE_DB_PATH, check_same_thread=False)
            cache_db.execute("PRAGMA journal_mode=WAL")
            cache_db.execute(
                "CREATE TABLE IF NOT EXISTS request_cache (key TEXT PRIMARY KEY, resp TEXT NOT NULL)"
            )
            cache_db.commit()
            if not aexit_registered:
                atexit.register(_close_cache_db)
                aexit_registered = True
    return cache_db


def load_cache():
    conn = _ensure_cache_db()
    if conn is None:
        return

    # One-time migration from legacy line-delimited cache file.
    if not os.path.exists(".requestcache"):
        return

    migrated_flag = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='request_cache_migration'"
    ).fetchone()
    if migrated_flag:
        return

    try:
        with open(".requestcache", "r") as file:
            rows = []
            for line in file.readlines():
                c = json.loads(line)
                if "key" in c and "resp" in c:
                    rows.append((c["key"], c["resp"]))
        if rows:
            with db_lock:
                conn.executemany(
                    "INSERT OR REPLACE INTO request_cache (key, resp) VALUES (?, ?)", rows
                )
                conn.execute("CREATE TABLE request_cache_migration (ok INTEGER NOT NULL)")
                conn.execute("INSERT INTO request_cache_migration (ok) VALUES (1)")
                conn.commit()
            log.info("migrated %s cache entries from .requestcache to %s", len(rows), CACHE_DB_PATH)
    except Exception:
        log.warning("failed to migrate legacy .requestcache file")


def get_from_cache(key: str) -> Optional[str]:
    conn = _ensure_cache_db()
    if conn is None:
        return None
    with db_lock:
        row = conn.execute("SELECT resp FROM request_cache WHERE key=?", (key,)).fetchone()
    if row:
        return row[0]
    return None


def add_to_cache(key: str, resp: str):
    conn = _ensure_cache_db()
    if conn is None:
        return
    with db_lock:
        conn.execute(
            "INSERT OR REPLACE INTO request_cache (key, resp) VALUES (?, ?)",
            (key, resp),
        )
        conn.commit()


def get_text_raw(cfg, url: str, key: str, fetchtext: Callable[[], str]):
    if not cfg.get("disable-cache"):
        cached = get_from_cache(key)
        if cached is not None:
            if not _looks_like_html(cached):
                log.warning("ignoring cached non-html payload for %s", url)
            if _is_block_page(cached):
                log.warning("ignoring cached security page for %s", url)
            else:
                if _looks_like_html(cached):
                    log.info("request to %s hit cache", url)
                    return cached

    tries = 10
    while True:
        try:
            resp = fetchtext()
            if not _looks_like_html(resp):
                raise RuntimeError("non-html payload returned")
            if _is_block_page(resp):
                raise RuntimeError("security verification page returned")
            if not cfg.get("disable-cache"):
                add_to_cache(key, resp)
            return resp
        except Exception as err:
            log.error(f"request to {url} failed:")
            log.error(traceback.format_exc())
            tries -= 1

            status = None
            if isinstance(err, requests.HTTPError) and err.response is not None:
                status = err.response.status_code

            if status == 403:
                # Small randomized backoff avoids rhythmic bursts that trigger anti-bot rules.
                sleep(random.uniform(0.1, 0.5))
            else:
                sleep(1)

            if tries > 0:
                log.warning("retrying...")
            else:
                break
    raise Exception(f'too many tries to URL "{url}"')


def make_key(obj) -> str:
    return binascii.hexlify(hashlib.blake2b(json.dumps(obj).encode(encoding='UTF-8')).digest()).decode("ascii")


def get_text(cfg, query: str) -> str:
    cookies = cfg.get("cookies")
    key = make_key({
        'm': 'get',
        'url': query,
        'cks': cookies,
    })

    def fetch():
        headers = {
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,image/apng,*/*;q=0.8",
            "Accept-Language": "es-ES,es;q=0.9",
            "Connection": "keep-alive",
            "Upgrade-Insecure-Requests": "1",
            "Sec-Fetch-Dest": "document",
            "Sec-Fetch-Mode": "navigate",
            "Sec-Fetch-Site": "none",
            "Sec-Fetch-User": "?1",
            "Cache-Control": "max-age=0",
            "DNT": "1",
            "Referer": "https://buscacursos.uc.cl/",
        }
        if cookies:
            headers["Cookie"] = cookies
        # Try cloudscraper first if available (for Cloudflare protection)
        if scraper:
            try:
                response = scraper.get(query, headers=headers, timeout=15)
            except Exception:
                response = session.get(query, headers=headers, timeout=15)
        else:
            response = session.get(query, headers=headers, timeout=15)
        response.raise_for_status()
        return response.text

    return get_text_raw(cfg, query, key, fetch)


def post_text(cfg, url: str, form_params: Dict[str, str]):
    cookies = cfg.get("cookies")
    key = make_key({
        'm': 'post',
        'url': url,
        'cks': cookies,
        'prm': form_params,
    })

    def post():
        headers = {
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,image/apng,*/*;q=0.8",
            "Accept-Language": "es-ES,es;q=0.9",
            "Connection": "keep-alive",
            "Upgrade-Insecure-Requests": "1",
            "Sec-Fetch-Dest": "document",
            "Sec-Fetch-Mode": "navigate",
            "Sec-Fetch-Site": "same-origin",
            "Sec-Fetch-User": "?1",
            "Cache-Control": "max-age=0",
            "DNT": "1",
            "Referer": "https://buscacursos.uc.cl/",
        }
        if cookies:
            headers["Cookie"] = cookies
        response = session.post(url, data=form_params, headers=headers, timeout=15)
        response.raise_for_status()
        return response.text

    return get_text_raw(cfg, f"{url} & {form_params}", key, post)
