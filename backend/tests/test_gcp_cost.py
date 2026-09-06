from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
COST = REPO_ROOT / "scripts" / "gcp_cost.py"
EXAMPLE = REPO_ROOT / "scripts" / "gcp_cost.example.json"


def _run_cost(tmp_path: Path, extra_config: str | None = None) -> dict:
    config_path = EXAMPLE
    if extra_config is not None:
        config_path = tmp_path / "gcp_cost_test_config.json"
        config_path.write_text(extra_config, encoding="utf-8")
    result = subprocess.run(
        [sys.executable, str(COST), "--config", str(config_path)],
        check=False,
        capture_output=True,
        text=True,
    )
    return {"rc": result.returncode, "stdout": result.stdout}


class TestGcpCost:
    def test_example_config_within_free_tier(self, tmp_path: Path) -> None:
        res = _run_cost(tmp_path)
        assert res["rc"] == 0
        out = json.loads(res["stdout"])
        assert out["within_free_tier"] is True
        assert out["total_monthly_usd"] == 0.0

    def test_is_deterministic(self, tmp_path: Path) -> None:
        a = _run_cost(tmp_path)
        b = _run_cost(tmp_path)
        assert json.loads(a["stdout"]) == json.loads(b["stdout"])
        assert a["stdout"] == b["stdout"]

    def test_flags_exceeding_free_tier_secrets(self, tmp_path: Path) -> None:
        over = (
            '{"monthly_requests": 100, "avg_cpu_seconds_per_request": 0.1, '
            '"avg_gib_seconds_per_request": 0.1, "storage_gib": 0, '
            '"secret_active_versions": 20, "secret_access_ops": 10, "neon_plan": "free"}'
        )
        res = _run_cost(tmp_path, over)
        assert res["rc"] == 1
        out = json.loads(res["stdout"])
        assert out["within_free_tier"] is False
        secrets = next(c for c in out["components"] if c["component"] == "secret_manager")
        assert secrets["free_tier_ok"] is False
        assert secrets["monthly_usd"] > 0
