from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SCANNER = REPO_ROOT / "scripts" / "scan_secrets.py"
JWT_64 = "A1b2C3d4" * 8

pytestmark = pytest.mark.security("SEC")


@pytest.fixture
def gitrepo(tmp_path: Path) -> Path:
    repo = tmp_path / "gitrepo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True, capture_output=True)
    subprocess.run(
        ["git", "config", "user.email", "scan@test"], cwd=repo, check=True, capture_output=True
    )
    subprocess.run(
        ["git", "config", "user.name", "scan-secrets"], cwd=repo, check=True, capture_output=True
    )
    return repo


def commit_file(gitrepo: Path, name: str, content: str) -> None:
    (gitrepo / name).write_text(content)
    subprocess.run(["git", "add", "-Af"], cwd=gitrepo, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-qm", "x"], cwd=gitrepo, check=True, capture_output=True)


def run_scanner(gitrepo: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCANNER), str(gitrepo)],
        capture_output=True,
        text=True,
        check=False,
    )


def test_flags_upper_case_secret(gitrepo: Path) -> None:
    commit_file(gitrepo, "config.env", f"JWT_SECRET={JWT_64}\n")
    commit_file(gitrepo, "notas.txt", "texto inocuo de la mananera\n")
    result = run_scanner(gitrepo)
    assert result.returncode == 1
    assert "config.env:1:jwt-secret" in result.stdout


def test_flags_demo_password_in_template(gitrepo: Path) -> None:
    pw = "RealP@ssw0rd123"
    commit_file(gitrepo, ".env.template", f"DEMO_USER_1_PASSWORD={pw}\n")
    result = run_scanner(gitrepo)
    assert result.returncode == 1
    assert ".env.template:1:template-non-placeholder" in result.stdout


def test_allows_documented_dev_default(gitrepo: Path) -> None:
    dev_pw = "mananeras"
    template = "POSTGRES_PASSWORD=" + dev_pw + "\n"
    template += "JWT_SECRET=\n"
    template += "DEMO_USER_2_PASSWORD=\n"
    commit_file(gitrepo, ".env.template", template)
    result = run_scanner(gitrepo)
    assert result.returncode == 0
    assert result.stdout == ""


def test_clean_file_passes(gitrepo: Path) -> None:
    commit_file(gitrepo, "x.txt", "texto inocuo de la mananera\nnota=123\n")
    result = run_scanner(gitrepo)
    assert result.returncode == 0
    assert result.stdout == ""


def test_flags_quoted_secret(gitrepo: Path) -> None:
    commit_file(gitrepo, "config.env", f'jwt_secret = "{JWT_64}"\n')
    result = run_scanner(gitrepo)
    assert result.returncode == 1
    assert "config.env:1:jwt-secret" in result.stdout
