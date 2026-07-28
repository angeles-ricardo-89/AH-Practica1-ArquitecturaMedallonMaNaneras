import hashlib
import re
from urllib.parse import parse_qs, urlencode, urlparse, urlunparse

import httpx

from lakehouse.log_config import get_logger

logger = get_logger(__name__, layer="bronze")

BASE_URL = "https://www.gob.mx"
ARTICLE_RE = re.compile(
    r'href="(/presidencia/es/articulos/[^"]+)"|href=\\"(/presidencia/es/articulos/[^\\"]+)\\"'
)
PAGE_RE = re.compile(r'page=(\d+)\\"')


def _extract_urls(html: str) -> list[str]:
    urls: list[str] = []
    for match in ARTICLE_RE.finditer(html):
        url = match.group(1) or match.group(2)
        if url:
            urls.append(f"{BASE_URL}{url}")
    return urls


def _fetch_page(client: httpx.Client, url: str) -> list[str]:
    resp = client.get(url)
    resp.raise_for_status()
    return _extract_urls(resp.text)


def _get_last_page(html: str) -> int:
    pages = [int(p) for p in PAGE_RE.findall(html)]
    return max(pages) if pages else 1


def fetch_article_list(archive_url: str, max_articles: int | None = None) -> list[str]:
    all_urls: list[str] = []
    with httpx.Client(timeout=30.0, follow_redirects=True) as client:
        resp = client.get(archive_url)
        resp.raise_for_status()
        html = resp.text
        last_page = _get_last_page(html)
        logger.info("Total pages detected: %d", last_page)

        page_urls = _extract_urls(html)
        all_urls.extend(page_urls)
        logger.info("Page 1: %d articles", len(page_urls))
        if max_articles is not None and len(all_urls) >= max_articles:
            logger.info("Reached max_articles=%s, stopping pagination", max_articles)
            return all_urls[:max_articles]

        parsed = urlparse(archive_url)
        base_params = parse_qs(parsed.query)
        base_params.setdefault("idiom", ["es"])
        base_params["order"] = ["DESC"]

        for page_num in range(2, last_page + 1):
            params = {**base_params, "page": [str(page_num)]}
            page_url = urlunparse(parsed._replace(query=urlencode(params, doseq=True)))
            page_articles = _fetch_page(client, page_url)
            all_urls.extend(page_articles)
            logger.info("Page %d: %d articles", page_num, len(page_articles))
            if max_articles is not None and len(all_urls) >= max_articles:
                logger.info("Reached max_articles=%s, stopping pagination", max_articles)
                return all_urls[:max_articles]

    logger.info("Total articles collected: %d", len(all_urls))
    return all_urls


def fetch_article_html(article_url: str) -> str:
    with httpx.Client(timeout=30.0, follow_redirects=True) as client:
        resp = client.get(article_url)
        resp.raise_for_status()
        return resp.text


def compute_content_hash(raw_html: str) -> str:
    main_match = re.search(r"<main[^>]*>(.*?)</main>", raw_html, re.DOTALL | re.IGNORECASE)
    content = main_match.group(0) if main_match else raw_html
    return hashlib.sha256(content.encode("utf-8")).hexdigest()
