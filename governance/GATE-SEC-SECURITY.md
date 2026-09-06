# GATE-SEC: Cobertura de Controles de Seguridad

**Status:** PERPETUO (siempre activo)
**Type:** Auto-check determinista (script-enforced)
**Enforcement:** Makefile targets — `make security` / `make security-report`

## Purpose

GATE-SEC garantiza que ningun control de seguridad OWASP materializado en el catalogo quede sin una prueba o chequeo que lo ejercite. Recorre `governance/security-controls.yaml` y verifica que cada control referencie archivos de prueba existentes con su marcador (`pytest.mark.security("<ID>")` en backend, `// security: <ID>` en frontend) y que los chequeos `lockfiles` y `secrets-scan` esten satisfechos.

## Activation

Commits y checkpoints de features que toquen autenticacion, memoria, agente, UI, configuracion o que introduzcan controles de seguridad nuevos en el catalogo.

## Exit Criteria

- [ ] `make security` sale con exit 0
- [ ] Todo control en `governance/security-controls.yaml` tiene una prueba/chequeo documentado que lo ejercita
- [ ] `scripts/scan_secrets.py` corre sin hallazgos (exit 0)
- [ ] Marcadores presentes: `pytest.mark.security("<ID>")` en backend, `// security: <ID>` en frontend
- [ ] Lockfiles presentes: `backend/uv.lock` y `frontend/pnpm-lock.yaml`

## Blocking Rule

- [ ] **BLOQUEO** si un control materializado no tiene prueba que lo ejercite
- [ ] **BLOQUEO** si un archivo de prueba referenciado en el catalogo no existe
- [ ] **BLOQUEO** si un archivo backend listado no contiene el marcador `pytest.mark.security("<ID>")`
- [ ] **BLOQUEO** si un archivo frontend listado no contiene el marcador `// security: <ID>`
- [ ] **BLOQUEO** si `scripts/scan_secrets.py` detecta un secreto rastreado por git

## How to Run

- `make security`: modo bloqueante (exit 1 si hay huecos de cobertura)
- `make security-report`: modo informativo (exit 0 siempre; imprime la matriz `ID | Control | Prueba/chequeo | Estado`)

El inspector es estatico: no requiere Postgres, red ni modelos. Resuelve las rutas del repo desde su propia ubicacion (`backend/scripts/security_check.py`), no desde el CWD.

## Relation to Other Gates

GATE-SEC corre dentro del ciclo del Gate Q (calidad por commit/checkpoint), pero no lo sustituye ni es sustituido por `make lint` o `make test-backend`: esos gates verifican calidad e integridad general; GATE-SEC verifica especificamente que cada control de seguridad materializado este vigilado por una prueba. La regla de bloqueo es independiente y acumulativa respecto de Gate S, Gate Q, Gate I y Gate QA.

## Related

- `governance/security-controls.yaml` (catalogo de controles)
- `backend/scripts/security_check.py` (inspector)
- `scripts/scan_secrets.py` (escaner de secretos)
- `AGENTS.md`
