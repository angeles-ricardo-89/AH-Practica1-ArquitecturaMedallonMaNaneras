# Spec — Base de datos de pruebas aislada

## 1. Objetivo

Los tests de integración que usan PostgreSQL escriben y borran datos en la base de datos de
producción/desarrollo `mananeras`, contaminando datos reales (ej. `DROP COLUMN IF EXISTS
embedding_3d` borra las coordenadas 3D generadas por el pipeline). Los tests deben usar una
base de datos `mananeras_test` separada, sin modificar ningún archivo de test existente.

DuckDB ya está aislado correctamente (`:memory:` en `test_idempotency.py`, `tmp_path` en
`test_duckdb_conn.py`, y `get_connection` mockeado en el resto). No requiere cambios.

## 2. Estado actual

- `Settings` (`config.py:10`) define `postgres_db: str = "mananeras"` como default.
- El archivo `.env` lo sobreescribe con `POSTGRES_DB=mananeras`.
- Los tests que tocan PostgreSQL construyen `Settings()` directamente, que lee de `.env` y
  variables de entorno, resultando en conexión a la DB de producción:
  - `test_cli.py` (`TestWritePipelineRun`) — `_write_pipeline_run` contra DB real
  - `test_api/test_observability.py` — fixtures que insertan/borran `pipeline_runs`
  - `test_api/test_embeddings_router.py` — inserta/borra filas con `embedding_3d`
  - `test_pipeline/test_observability_conn.py` — crea/destruye schema `observability` y hace
    `DROP COLUMN IF EXISTS embedding_3d` en `gold.rag_corpus`
- DuckDB usa `:memory:` o `tmp_path` en todos los tests; no hay riesgo de contaminación.
- No existe `conftest.py` en `backend/tests/`.

## 3. Diseño

### 3.1 Override global vía variable de entorno

pydantic-settings da prioridad a las variables de entorno sobre el archivo `.env`. Si seteamos
`POSTGRES_DB=mananeras_test` en el entorno antes de que cualquier test construya `Settings()`,
todos los tests automáticamente usarán la DB de pruebas.

### 3.2 Creación de la DB de pruebas en `pytest_configure`

`pytest_configure` se ejecuta antes de la recolección de tests, garantizando que la variable
esté seteada antes de cualquier `Settings()`.

Para crear la DB, nos conectamos al admin database `postgres` (siempre existe) en el mismo
contenedor pgvector, y ejecutamos `CREATE DATABASE mananeras_test`. La extensión `vector` se
instala con `CREATE EXTENSION IF NOT EXISTS vector`.

### 3.3 Archivo: `backend/tests/conftest.py` (nuevo)

```python
import os
import psycopg

TEST_DB = "mananeras_test"


def pytest_configure(config):
    os.environ["POSTGRES_DB"] = TEST_DB

    admin_conn = "postgresql://mananeras:mananeras@localhost:5433/postgres"
    try:
        with psycopg.connect(admin_conn) as conn:
            conn.autocommit = True
            conn.execute(f"CREATE DATABASE {TEST_DB}")
    except psycopg.errors.DuplicateDatabase:
        pass
```

- El `CREATE DATABASE` falla silenciosamente si la DB ya existe (segunda ejecución de tests).
- La extensión `vector` no necesita crearse explícitamente: los tests que usan `gold.rag_corpus`
  con tipo `vector(768)` (ej. `test_embeddings_router.py`) crean la tabla vía `ensure_gold_tables`,
  que asume que la extensión está disponible. En la imagen `pgvector/pgvector:pg17` la extensión
  está compilada en el servidor; las tablas que usan `vector(768)` funcionan sin `CREATE EXTENSION`
  explícito en la DB de pruebas porque el tipo está disponible a nivel servidor. Si se requiere,
  se agrega `CREATE EXTENSION IF NOT EXISTS vector` tras el `CREATE DATABASE` conectándose a la
  nueva DB.

### 3.4 DuckDB — sin cambios

Los tests ya usan:
- `duckdb.connect(":memory:")` — `test_idempotency.py`
- `tmp_path / "test.duckdb"` — `test_duckdb_conn.py`
- `@patch("lakehouse.cli.get_connection")` — `test_cli.py` y resto

Ningún test lee o escribe el archivo de producción `data/lakehouse/ducklake_files.duckdb`.

## 4. Impacto

| Componente | Cambio |
|---|---|
| `backend/tests/conftest.py` | Nuevo archivo |
| `backend/src/lakehouse/config.py` | Sin cambios |
| `backend/.env` | Sin cambios |
| `docker-compose.yml` | Sin cambios |
| Archivos de test existentes | Cero cambios |
| DuckDB | Sin cambios |

## 5. Casos borde

1. **Postgres no disponible** al ejecutar tests → `pytest_configure` lanza `psycopg.OperationalError`
   con mensaje claro: "No se pudo conectar a PostgreSQL para crear la base de datos de pruebas".
2. **Segunda ejecución de tests** → `CREATE DATABASE` lanza `DuplicateDatabase`, capturado y
   silenciado.
3. **Variables de entorno ya presentes** (CI) → `os.environ["POSTGRES_DB"]` sobreescribe cualquier
   valor previo.
4. **Datos de una ejecución anterior** en `mananeras_test` → los tests que limpian sus datos
   (`DELETE FROM ... WHERE capa = 'bronze'`, `_drop_observability_schema`, etc.) lo manejan.
5. **Tests que usan `monkeypatch.setattr(Settings, ...)`** → siguen funcionando; el `monkeypatch`
   pisa el atributo de clase, no la variable de entorno.

## 6. Criterios de éxito

1. `uv run pytest` pasa completo (441 tests) sin tocar la DB `mananeras`.
2. La DB `mananeras_test` contiene solo datos generados por tests, nunca datos del pipeline.
3. La DB `mananeras` conserva sus datos intactos tras ejecutar el test suite.
4. `ruff check`, `ty check`, coverage ≥ 90% (sin cambios en código fuente, solo conftest).
