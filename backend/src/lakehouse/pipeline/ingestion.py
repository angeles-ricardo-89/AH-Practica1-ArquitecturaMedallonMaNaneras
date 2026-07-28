import asyncio
import httpx
from datetime import UTC, datetime
from typing import List

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
        max_retries: int = 3,
    ) -> None:
        self.db_path = db_path
        self.source_archive_url = source_archive_url
        self.max_articles = max_articles
        self.max_retries = max_retries

    async def _worker(
        self,
        queue: asyncio.Queue,
        client: httpx.AsyncClient,
        ingestion_run_id: str,
        conn,
    ) -> int:
        """Worker to consume URLs from the queue and process them."""
        records_inserted = 0
        while True:
            url = await queue.get()
            if url is None:
                queue.task_done()
                break

            raw_html = None
            for attempt in range(1, self.max_retries + 1):
                try:
                    # Use httpx to fetch HTML
                    response = await client.get(url, follow_redirects=True)
                    response.raise_for_status()
                    raw_html = response.text
                    break
                except (httpx.HTTPError, httpx.TimeoutException) as e:
                    if attempt == self.max_retries:
                        logger.error("Error máximo de reintentos alcanzado para URL", url=url, error=str(e))
                    else:
                        logger.warning("Reintento de descarga", url=url, attempt=attempt, error=str(e))
                        await asyncio.sleep(1 * attempt)  # Exponential backoff simple

            if raw_html:
                content_hash = compute_content_hash(raw_html)
                # Use to_thread for synchronous DB operations
                inserted = await asyncio.to_thread(
                    insert_bronze_record,
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
            
            queue.task_done()
        
        return records_inserted

    async def run(self, dry_run: bool = False) -> dict:
        ingestion_run_id = datetime.now(UTC).strftime("run_%Y%m%d_%H%M%S")
        logger.info("Iniciando ingesta Bronze (Async)", run_id=ingestion_run_id)

        article_urls = fetch_article_list(self.source_archive_url, max_articles=self.max_articles)
        html_count = len(article_urls)
        logger.info("Artículos encontrados para descargar", cantidad=html_count)

        records_inserted = 0

        if not dry_run:
            conn = get_connection(self.db_path)
            ensure_bronze_table(conn)

            # Configuración del Worker Pool
            # El número de workers viene de la configuración, pero lo tomamos de la instancia 
            # o podemos pasar un pool_size si es necesario. 
            # Como Ingestor no tiene pool_size en __init__, usaremos un default o 
            # lo pasaremos por otro medio. Para este refactor, asumiremos que 
            # el pool_size se puede pasar en el constructor o es una propiedad.
            # Pero para mantener la firma, usaremos un valor por defecto o 
            # lo leeremos de la configuración si es necesario.
            # El plan decía MAX_INGEST_POOL.
            
            # Vamos a asumir que el pool_size es parte de la configuración del Ingestor 
            # para este diseño.
            from lakehouse.config import Settings
            settings = Settings()
            pool_size = settings.max_ingest_pool

            queue = asyncio.Queue()
            for url in article_urls:
                queue.put_nowait(url)

            # Añadir centinelas para detener los workers
            for _ in range(pool_size):
                queue.put_nowait(None)

            async with httpx.AsyncClient(timeout=httpx.Timeout(30.0)) as client:
                workers = [
                    asyncio.create_task(self._worker(queue, client, ingestion_run_id, conn))
                    for _ in range(pool_size)
                ]
                
                # Esperar a que todos los workers terminen
                results = await asyncio.gather(*workers)
                records_inserted = sum(results)

            conn.close()
            logger.info(
                "Ingesta Bronze completada",
                run_id=ingestion_run_id,
                html_count=html_count,
                records_inserted=records_inserted,
            )
        else:
            # En dry_run simplemente simulamos el conteo
            records_inserted = html_count

        return {
            "ingestion_run_id": ingestion_run_id,
            "html_count": html_count,
            "records_inserted": records_inserted,
        }

