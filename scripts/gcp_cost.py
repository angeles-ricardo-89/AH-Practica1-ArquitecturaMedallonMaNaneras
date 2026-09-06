#!/usr/bin/env python3
"""Costo mensual estimado de la infraestructura productiva (determinista, ~USD 0).

Herramienta pura de calculo: misma entrada -> misma salida. NO llama a APIs de
precios ni a la red. Los precios y niveles gratuitos estan congelados en el
snapshot embebido (fecha + fuente).

Uso:
    python scripts/gcp_cost.py --config scripts/gcp_cost.example.json

Salida: JSON con costo mensual por componente, flags de free-tier excedido,
suposiciones y total. Si algun componente excede su nivel gratuito, termina con
exit code 1 para bloquear el despliegue hasta reconsiderar.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from typing import Any

PRICE_SNAPSHOT = {
    "date": "2026-09-05",
    "source": (
        "https://cloud.google.com/run/pricing, https://cloud.google.com/secret-manager/pricing, "
        "https://ai.google.dev/gemini-api/docs/pricing, https://neon.com/pricing"
    ),
    # Precios por unidad despues del nivel gratuito (USD).
    "cloud_run_cpu_second_usd": 0.000024,
    "cloud_run_gib_second_usd": 0.0000025,
    "cloud_run_request_per_million_usd": 0.40,
    "cloud_run_storage_gib_month_usd": 0.026,
    # Niveles gratuitos mensuales de Cloud Run (regiones de EE.UU., us-central1).
    "cloud_run_free_cpu_seconds": 180_000,
    "cloud_run_free_gib_seconds": 360_000,
    "cloud_run_free_requests": 2_000_000,
    # Secret Manager: gratis 6 versiones activas y 10.000 accesos.
    "secret_manager_free_active_versions": 6,
    "secret_manager_free_access_ops": 10_000,
    "secret_manager_extra_version_month_usd": 0.06,
    "secret_manager_access_ops_per_10k_usd": 0.03,
    # Gemini Flash-Lite y Embeddings: nivel gratuito (con aviso de uso de datos).
    "gemini_free_tier_note": "Nivel gratuito de Gemini con aviso de uso de datos aceptado",
}


@dataclass(frozen=True)
class ComponentCost:
    name: str
    monthly_usd: float
    free_tier_ok: bool
    notes: list[str]


def _cloud_run(config: dict[str, Any]) -> ComponentCost:
    requests = float(config.get("monthly_requests", 0))
    cpu_seconds = requests * float(config.get("avg_cpu_seconds_per_request", 0))
    gib_seconds = requests * float(config.get("avg_gib_seconds_per_request", 0))
    storage_gib = float(config.get("storage_gib", 0))

    cost = 0.0
    notes: list[str] = []
    if cpu_seconds > PRICE_SNAPSHOT["cloud_run_free_cpu_seconds"]:
        excess = cpu_seconds - PRICE_SNAPSHOT["cloud_run_free_cpu_seconds"]
        cost += excess * PRICE_SNAPSHOT["cloud_run_cpu_second_usd"]
        notes.append(f"vCPU-seg fuera de free tier: {excess:.0f}")
    if gib_seconds > PRICE_SNAPSHOT["cloud_run_free_gib_seconds"]:
        excess = gib_seconds - PRICE_SNAPSHOT["cloud_run_free_gib_seconds"]
        cost += excess * PRICE_SNAPSHOT["cloud_run_gib_second_usd"]
        notes.append(f"GiB-seg fuera de free tier: {excess:.0f}")
    if requests > PRICE_SNAPSHOT["cloud_run_free_requests"]:
        excess = requests - PRICE_SNAPSHOT["cloud_run_free_requests"]
        cost += excess / 1_000_000 * PRICE_SNAPSHOT["cloud_run_request_per_million_usd"]
        notes.append(f"solicitudes fuera de free tier: {excess:.0f}")
    cost += storage_gib * PRICE_SNAPSHOT["cloud_run_storage_gib_month_usd"]
    notes.append("Escala a cero con max 1 instancia (sin costo base por instancia)")
    return ComponentCost("cloud_run", round(cost, 4), cost == 0.0, notes)


def _secret_manager(config: dict[str, Any]) -> ComponentCost:
    versions = int(config.get("secret_active_versions", 0))
    access_ops = int(config.get("secret_access_ops", 0))
    cost = 0.0
    notes: list[str] = []
    if versions > PRICE_SNAPSHOT["secret_manager_free_active_versions"]:
        excess = versions - PRICE_SNAPSHOT["secret_manager_free_active_versions"]
        cost += excess * PRICE_SNAPSHOT["secret_manager_extra_version_month_usd"]
        notes.append(f"versiones activas fuera de free tier: {excess}")
    if access_ops > PRICE_SNAPSHOT["secret_manager_free_access_ops"]:
        excess = access_ops - PRICE_SNAPSHOT["secret_manager_free_access_ops"]
        cost += excess / 10_000 * PRICE_SNAPSHOT["secret_manager_access_ops_per_10k_usd"]
        notes.append(f"accesos fuera de free tier: {excess}")
    notes.append(f"{versions} versiones activas, {access_ops} accesos/mes")
    return ComponentCost("secret_manager", round(cost, 4), cost == 0.0, notes)


def _gemini(_config: dict[str, Any]) -> ComponentCost:
    return ComponentCost(
        "gemini_models",
        0.0,
        True,
        [PRICE_SNAPSHOT["gemini_free_tier_note"]],
    )


def _neon(config: dict[str, Any]) -> ComponentCost:
    plan = str(config.get("neon_plan", "free"))
    ok = plan == "free"
    notes = [
        "Plan gratuito con escala a cero; vigilar cuota de computo"
        if ok
        else f"Plan '{plan}' fuera del nivel gratuito"
    ]
    return ComponentCost("neon", 0.0, ok, notes)


COMPONENTS = {
    "cloud_run": _cloud_run,
    "secret_manager": _secret_manager,
    "gemini": _gemini,
    "neon": _neon,
}


def compute(config: dict[str, Any]) -> dict[str, Any]:
    results: list[dict[str, Any]] = []
    total = 0.0
    all_ok = True
    for name in sorted(COMPONENTS):
        comp = COMPONENTS[name](config)
        results.append(
            {
                "component": comp.name,
                "monthly_usd": comp.monthly_usd,
                "free_tier_ok": comp.free_tier_ok,
                "notes": comp.notes,
            }
        )
        total += comp.monthly_usd
        all_ok = all_ok and comp.free_tier_ok

    output = {
        "snapshot": PRICE_SNAPSHOT["date"],
        "snapshot_source": PRICE_SNAPSHOT["source"],
        "input_hash": json.dumps(config, sort_keys=True),
        "components": results,
        "total_monthly_usd": round(total, 4),
        "assumptions": [
            "Cloud Run por solicitud con escala a cero y max 1 instancia",
            "Neon en plan gratuito con cuota de computo vigilada",
            "Gemini en nivel gratuito con aviso de uso de datos aceptado",
            "Secret Manager dentro de 6 versiones activas y 10k accesos",
        ],
        "within_free_tier": all_ok,
    }
    return output


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", required=True, help="JSON de config de recursos")
    args = parser.parse_args()

    with open(args.config, encoding="utf-8") as fh:
        config = json.load(fh)

    output = compute(config)
    print(json.dumps(output, indent=2, ensure_ascii=False))
    if not output["within_free_tier"]:
        print(
            "ERROR: algun componente excede su nivel gratuito; reconsidera antes de aplicar.",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
