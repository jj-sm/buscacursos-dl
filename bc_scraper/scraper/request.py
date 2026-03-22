import os
import traceback
from typing import Callable, Dict
import requests
from time import sleep
import logging
import hashlib
import json
import binascii


log = logging.getLogger("scraper")


def _is_block_page(resp: str) -> bool:
    return "Verificación de Seguridad" in resp or "challenge-container" in resp


def _looks_like_html(resp: str) -> bool:
    sample = resp[:2048].lower()
    return "<html" in sample or "<!doctype html" in sample

cache = {}
cachefile = None
session = requests.Session()

try:
    import cloudscraper
    HAS_CLOUDSCRAPER = True
    scraper = cloudscraper.create_scraper()
except Exception:
    HAS_CLOUDSCRAPER = False
    scraper = None
def load_cache():
    global cachefile
    
    if os.path.exists(".requestcache"):
        with open(".requestcache", 'r') as file:
            for line in file.readlines():
                c = json.loads(line)
                cache[c['key']] = c['resp']
    cachefile = open(".requestcache", 'a')


def add_to_cache(key: str, resp: str):
    cache[key] = resp
    if cachefile:
        json.dump({'key': key, 'resp': resp}, cachefile)
        cachefile.write('\n')
        cachefile.flush()


def get_text_raw(cfg, url: str, key: str, fetchtext: Callable[[], str]):
    if not cfg.get("disable-cache"):
        if key in cache:
            cached = cache[key]
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
        except Exception:
            log.error(f"request to {url} failed:")
            log.error(traceback.format_exc())
            tries -= 1
            sleep(1)
            if tries > 0:
                log.log("retrying...")
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
