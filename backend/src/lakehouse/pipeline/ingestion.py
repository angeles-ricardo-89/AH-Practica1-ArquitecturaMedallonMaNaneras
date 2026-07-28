from datetime import UTC, datetime

from lakehouse.db.duckdb_conn import (
    ensure_bronze_table,
    get_connection,
    insert_bronze_record,
)
from lakehouse.log_config import get_logger
from lakehouse.pipeline.scraper import (
    compute_content_hash,
    fetch_article_html,
    fetch_article_list,
)

logger = get_logger(__name__, layer="bronze")


class Ingestor:
    def __init__(
        self,
        db_path: str,
        source_archive_url: str,
        max_articles: int | None = None,
    ) -> None:
        self.db_path = db_path
        self.source_archive_url = source_archive_url
        self.max_articles = max_articles

    def run(self, dry_run: bool = False) -> dict:
        ingestion_run_id = datetime.now(UTC).strftime("run_%Y%m%d_%H%M%S")
        logger.info("Iniciando ingesta Bronze", run_id=ingestion_run_id)

        article_urls = fetch_article_list(self.source_archive_url, max_articles=self.max_articles)
        html_count = len(article_urls)
        logger.info("Artículos encontrados para descargar", cantidad=html_count)

        records_inserted = 0

        if not dry_run:
            conn = get_connection(self.db_path)
            ensure_bronze_table(conn)

            for url in article_urls:
                raw_html = fetch_article_html(url)
                content_hash = compute_content_hash(raw_html)
                inserted = insert_bronze_record(
                    conn,
                    ingestion_run_id=ingestion_run_id,
                    source_url=url,
                    raw_html=raw_html,
                    content_hash=content_hash,
                )
                if inserted:
                    records_inserted += 1
                    logger.info("Artículo insertado en Bronze", url=url, hash=content_hash)
                else:
                    logger.warning("Artículo duplicado, omitido", url=url, hash=content_hash)

            conn.close()
            logger.info(
                "Ingesta Bronze completada",
                run_id=ingestion_run_id,
                html_count=html_count,
                records_inserted=records_inserted,
            )

        return {
            "ingestion_run_id": ingestion_run_id,
            "html_count": html_count,
            "records_inserted": records_inserted,
        }
