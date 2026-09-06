# Tech Skill: Testing de Seguridad (marcadores OWASP + catalogo + GATE-SEC)

## Proposito

Definir como se escriben pruebas de seguridad TRAZABLES a controles en este repo. El catalogo
`governance/security-controls.yaml` es la fuente de verdad: declara por control (id OWASP) los
archivos de prueba que lo ejercitan. El inspector determinista `backend/scripts/security_check.py`
verifica solo existencia de archivo + presencia del marcador, sin heuristica, sin Postgres y sin
red. `make security` bloquea; `make security-report` informa.

## Referencias

- Testing + QA: `../tech/testing_qa.md`
- Python + uv + Ruff: `../tech/python_uv_ruff.md`

## Marcadores por stack

- **Backend:** `pytest.mark.security("<ID>")`, con el id OWASP del control (A07, A04, CSRF, A01,
  A05, LLM01, LLM03, LLM08, HDRS, A10, ...). El marcador se registra en `[tool.pytest.ini_options]`
  de `backend/pyproject.toml` para evitar warnings. Cuando un archivo cubre VARIOS controles, se
  declara una lista a nivel de modulo:

```python
from __future__ import annotations

import pytest

pytestmark = [
    pytest.mark.security("HDRS"),
    pytest.mark.security("A10"),
]
```

- **Frontend:** comentario en el archivo de test: `// security: LLM10`.

## Catalogo (governance/security-controls.yaml)

Cada control tiene `id`, `title`, `family` (skill de dominio), `control` y listas de pruebas:

```yaml
controls:
  - id: A07
    title: Authentication Failures
    family: security-auth-jwt
    control: mensaje generico, limite de login, expiracion JWT
    backend_tests:
      - tests/test_api/test_auth.py
    frontend_tests: []
    checks: []
  - id: A03
    title: Supply Chain
    family: security-headers-config
    control: lockfiles presentes, dependencias fijadas
    backend_tests: []
    frontend_tests: []
    checks:
      - lockfiles
```

- `backend_tests`: rutas relativas a `backend/` que deben contener `pytest.mark.security("<ID>")`.
- `frontend_tests`: rutas relativas a `frontend/` que deben contener `// security: <ID>`.
- `checks`: chequeos estaticos que ejecuta el inspector (`lockfiles` verifica `backend/uv.lock` y
  `frontend/pnpm-lock.yaml`; `secrets-scan` invoca `scripts/scan_secrets.py`).

## Gate GATE-SEC

```bash
make security         # cd backend && uv run python scripts/security_check.py --check  (bloquea)
make security-report  # cd backend && uv run python scripts/security_check.py --report (informa)
```

Reglas de bloqueo: control sin prueba registrada, archivo de prueba inexistente, marcador ausente
en un archivo listado, o secreto detectado por `scripts/scan_secrets.py`.

## Anadir un control nuevo (pasos)

1. Implementar el control y su prueba unitaria/integracion real (no mocks de servicios internos).
2. Anadir la entrada en `governance/security-controls.yaml` con su id OWASP y las rutas de prueba.
3. Anadir el marcador correspondiente en cada archivo de prueba (`pytest.mark.security("<ID>")`
   backend o `// security: <ID>` frontend). Si el archivo ya tiene `pytestmark`, convertirlo en
   lista y agregar el id.
4. Actualizar la skill de dominio de la familia si el control es nuevo (y AGENTS.md).
5. Correr `make security-report` para ver la matriz y `make security` para confirmar exit 0.

## Reglas

- El marcador SIEMPRE lleva el id del catalogo, en mayusculas, exacto; el inspector compara substrings.
- No hay id inventado: si no existe en el catalogo, primero se agrega al YAML.
- Prohibido saltar el gate con `--report` en un commit: `--check` es el modo de bloqueo.
- Las pruebas de seguridad siguen el ciclo de Gate Q (cobertura >= 90%, ruff, ty) ademas de GATE-SEC.

## Verificaciones

- [ ] `make security` sale con exit 0 despues de tocar un control o su prueba.
- [ ] `make security-report` muestra la matriz completa sin huecos.
- [ ] Todo id del catalogo tiene al menos una prueba o chequeo que lo ejercita.
