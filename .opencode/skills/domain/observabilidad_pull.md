# Domain Skill: Observabilidad Pull

## Proposito

Definir el mecanismo de observabilidad del pipeline, donde el dashboard Vue consulta activamente
el estado del sistema via endpoints HTTP del backend. No se usa push (WebSockets, SSE) en el MVP.

## Tech Skills de Referencia

| Tech Skill | Archivo | Como la usa |
|------------|---------|-------------|
| FastAPI + Pydantic + Typer | `../tech/fastapi_pydantic_typer.md` | Endpoints de observabilidad en FastAPI |
| Vue 3 + Pinia + Tailwind | `../tech/vue3_pinia_tailwind.md` | SemaforoEstado + LogViewer en dashboard |

## Principio: Observabilidad Pull

El dashboard Vue NO recibe eventos del backend. En cambio, consulta periodicamente:

- **GET /observability/status** → estado actual del pipeline (semaforo).
- **GET /observability/logs** → ultimas lineas del archivo de log del cron.

El frontend hace polling cada 10 segundos via `setInterval`.

### Endpoint: Estado del Pipeline

```python
from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

from fastapi import APIRouter

from lakehouse.schemas.observability import PipelineStatus, SemaforoColor

router = APIRouter(prefix="/observability", tags=["observability"])


@router.get(
    "/status",
    response_model=PipelineStatus,
    summary="Estado actual del pipeline de ingesta",
)
async def get_pipeline_status() -> PipelineStatus:
    semaforo_file = Path("/data/lakehouse/logs/cron.status")
    if not semaforo_file.exists():
        return PipelineStatus(
            status="unknown",
            color=SemaforoColor.GRAY,
            last_run=None,
            message="No hay registro de ejecucion del pipeline",
        )

    data = semaforo_file.read_text().strip().split("\n")
    return PipelineStatus(
        status=data[0],
        color=SemaforoColor(data[1]),
        last_run=data[2] if len(data) > 2 else None,
        message=data[3] if len(data) > 3 else "",
    )
```

### Endpoint: Lectura de Logs

```python
@router.get(
    "/logs",
    response_model=PipelineLogs,
    summary="Ultimas lineas del log del pipeline",
)
async def get_pipeline_logs(
    lines: int = 50,
    tail: int = 200,
) -> PipelineLogs:
    log_path = Path("/data/lakehouse/logs/pipeline/cron.log")
    if not log_path.exists():
        return PipelineLogs(lines=[], total_lines=0)

    # Leer ultimas N lineas sin cargar todo el archivo en memoria
    with open(log_path) as f:
        all_lines = f.readlines()

    total = len(all_lines)
    recent = all_lines[-lines:] if lines > 0 else all_lines

    return PipelineLogs(
        lines=[line.strip() for line in recent],
        total_lines=total,
    )
```

### Schemas de Observabilidad

```python
from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict


class SemaforoColor(StrEnum):
    GREEN = "green"
    YELLOW = "yellow"
    RED = "red"
    GRAY = "gray"


class PipelineStatus(BaseModel):
    model_config = ConfigDict(frozen=True)

    status: str  # "running", "completed", "failed", "unknown"
    color: SemaforoColor
    last_run: str | None
    message: str


class PipelineLogs(BaseModel):
    lines: list[str]
    total_lines: int
```

### Escritura del Semaforo (Backend/Pipeline)

```python
from __future__ import annotations

from pathlib import Path


def write_pipeline_status(
    status: str,
    color: str,
    message: str = "",
) -> None:
    semaforo_file = Path("/data/lakehouse/logs/cron.status")
    semaforo_file.parent.mkdir(parents=True, exist_ok=True)
    from datetime import datetime

    now = datetime.now().isoformat()
    semaforo_file.write_text(f"{status}\n{color}\n{now}\n{message}")
```

### Polling en el Frontend (Vue + Pinia)

```typescript
// stores/observability.ts
import { defineStore } from "pinia";
import { ref, onMounted, onUnmounted } from "vue";
import { observabilityAPI } from "@/api/observability";

export const useObservabilityStore = defineStore("observability", () => {
  const status = ref<"green" | "yellow" | "red" | "gray">("gray");
  const lastRun = ref<string | null>(null);
  const logs = ref<string[]>([]);
  const message = ref("");
  let intervalId: ReturnType<typeof setInterval> | null = null;

  async function fetchStatus() {
    try {
      const data = await observabilityAPI.getStatus();
      status.value = data.color;
      lastRun.value = data.last_run;
      message.value = data.message;
    } catch {
      status.value = "red";
      message.value = "Error al conectar con el backend";
    }
  }

  async function fetchLogs() {
    try {
      const data = await observabilityAPI.getLogs(50);
      logs.value = data.lines;
    } catch {
      logs.value = ["Error al leer logs"];
    }
  }

  function startPolling(intervalMs = 10_000) {
    fetchStatus();
    fetchLogs();
    intervalId = setInterval(() => {
      fetchStatus();
      fetchLogs();
    }, intervalMs);
  }

  function stopPolling() {
    if (intervalId) {
      clearInterval(intervalId);
      intervalId = null;
    }
  }

  onMounted(() => startPolling());
  onUnmounted(() => stopPolling());

  return { status, lastRun, logs, message, startPolling, stopPolling };
});
```

### Componente SemaforoEstado.vue

```vue
<script setup lang="ts">
import { useObservabilityStore } from "@/stores/observability";
import { computed } from "vue";

const obs = useObservabilityStore();

const colorClass = computed(() => ({
  green: "bg-emerald-500",
  yellow: "bg-yellow-500",
  red: "bg-red-500",
  gray: "bg-gray-500",
}[obs.status]));

const statusLabel = computed(() => ({
  green: "Operativo",
  yellow: "Degradado",
  red: "Error",
  gray: "Desconocido",
}[obs.status]));
</script>

<template>
  <div class="flex items-center gap-3 p-4 bg-gray-800 rounded-lg">
    <div :class="colorClass" class="w-4 h-4 rounded-full animate-pulse" />
    <div>
      <p class="font-semibold">{{ statusLabel }}</p>
      <p v-if="obs.lastRun" class="text-xs text-gray-400">
        Ultima ejecucion: {{ obs.lastRun }}
      </p>
      <p v-if="obs.message" class="text-xs text-gray-500">{{ obs.message }}</p>
    </div>
  </div>
</template>
```

## Checklist de Verificacion

- [ ] `GET /observability/status` devuelve 200 con PipelineStatus valido.
- [ ] `GET /observability/logs?lines=50` devuelve ultimas 50 lineas del log.
- [ ] Semaforo cambia entre green/yellow/red/gray correctamente.
- [ ] Pipeline escribe el archivo cron.status al iniciar y finalizar.
- [ ] Dashboard hace polling cada 10 segundos.
- [ ] LogViewer muestra logs sin necesidad de SSH.
- [ ] En caso de error de conexion, el semaforo se pone en rojo.
