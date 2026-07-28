import pytest
import httpx
from lakehouse.pipeline.ingestion import Ingestor
from unittest.mock import AsyncMock, patch

@pytest.mark.asyncio
async def test_ingestor_run_async():
    # Mocking dependencies to test async flow
    with patch("lakehouse.pipeline.ingestion.fetch_article_list", return_value=["http://test.com/1", "http://test.com/2"]), \
         patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get, \
         patch("lakehouse.db.duckdb_conn.get_connection") as mock_conn, \
         patch("lakehouse.db.duckdb_conn.ensure_bronze_table") as mock_ensure, \
         patch("lakehouse.pipeline.ingestion.insert_bronze_record", new_callable=AsyncMock) as mock_insert:
    
        # Setup mock response
        mock_response = AsyncMock()
        mock_response.text = "<html>test</html>"
        mock_response.status_code = 200
        mock_get.return_value = mock_response
    
        mock_insert.return_value = True
    
        ingestor = Ingestor(db_path="test.db", source_archive_url="http://test.com", max_articles=2)
        result = await ingestor.run()
    
        assert result["html_count"] == 2
        assert mock_get.call_count == 2

