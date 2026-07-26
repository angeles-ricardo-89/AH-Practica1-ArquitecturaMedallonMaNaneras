import hashlib
import re

import httpx


def fetch_article_list(archive_url: str) -> list[str]:
    with httpx.Client(timeout=30.0, follow_redirects=True) as client:
        resp = client.get(archive_url)
        resp.raise_for_status()
        html = resp.text
    pattern = re.compile(r'href="(/presidencia/es/articulo/[^"]+)"')
    matches = pattern.findall(html)
    base_url = "https://www.gob.mx"
    return [f"{base_url}{m}" for m in matches]


def fetch_article_html(article_url: str) -> str:
    with httpx.Client(timeout=30.0, follow_redirects=True) as client:
        resp = client.get(article_url)
        resp.raise_for_status()
        return resp.text


def compute_content_hash(raw_html: str) -> str:
    main_match = re.search(r"<main[^>]*>(.*?)</main>", raw_html, re.DOTALL | re.IGNORECASE)
    content = main_match.group(0) if main_match else raw_html
    return hashlib.sha256(content.encode("utf-8")).hexdigest()
