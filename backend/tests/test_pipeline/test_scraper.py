from unittest.mock import Mock, patch

from lakehouse.pipeline.scraper import compute_content_hash, fetch_article_html, fetch_article_list

SAMPLE_ARCHIVE_HTML = """
<html><body>
<div class="article-list">
  <article>
    <a href="/presidencia/es/articulos/versiones-estenograficas-conferencia-matutina-2024-10-01">Conferencia 1 oct</a>
  </article>
  <article>
    <a href="/presidencia/es/articulos/otra-conferencia-2024-10-02">Conferencia 2 oct</a>
  </article>
</div>
</body></html>
"""


class TestFetchArticleList:
    @patch("lakehouse.pipeline.scraper.httpx.Client")
    def test_parses_article_urls(self, mock_client):
        mock_resp = Mock()
        mock_resp.text = SAMPLE_ARCHIVE_HTML
        mock_resp.raise_for_status = Mock()
        mock_client.return_value.__enter__.return_value.get.return_value = mock_resp

        urls = fetch_article_list("https://www.gob.mx/presidencia/es/archivo/articulos")
        assert len(urls) == 2
        assert "2024-10-01" in urls[0]
        assert "2024-10-02" in urls[1]

    @patch("lakehouse.pipeline.scraper.httpx.Client")
    def test_empty_archive_returns_empty_list(self, mock_client):
        mock_resp = Mock()
        mock_resp.text = "<html><body>No articles</body></html>"
        mock_resp.raise_for_status = Mock()
        mock_client.return_value.__enter__.return_value.get.return_value = mock_resp

        urls = fetch_article_list("https://example.com/empty")
        assert urls == []


class TestFetchArticleHtml:
    @patch("lakehouse.pipeline.scraper.httpx.Client")
    def test_fetches_html(self, mock_client):
        mock_resp = Mock()
        mock_resp.text = "<html><body><main>Conferencia content</main></body></html>"
        mock_resp.raise_for_status = Mock()
        mock_client.return_value.__enter__.return_value.get.return_value = mock_resp

        html = fetch_article_html("https://example.com/article")
        assert "<main>" in html


class TestComputeContentHash:
    def test_deterministic_hash(self):
        html1 = "<html><body><main>Same content</main></body></html>"
        html2 = "<html><body><main>Same content</main></body></html>"
        h1 = compute_content_hash(html1)
        h2 = compute_content_hash(html2)
        assert h1 == h2

    def test_different_html_different_hash(self):
        html1 = "<html><body><main>Content A</main></body></html>"
        html2 = "<html><body><main>Content B</main></body></html>"
        h1 = compute_content_hash(html1)
        h2 = compute_content_hash(html2)
        assert h1 != h2

    def test_returns_64_char_hex(self):
        h = compute_content_hash("<html><body><main>Test</main></body></html>")
        assert len(h) == 64
        assert all(c in "0123456789abcdef" for c in h)
