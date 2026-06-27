from __future__ import annotations

import os
import shlex
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parent
SERVICE_NAME = os.getenv("SERVICE_NAME", "drebolvpn")
REPO_URL = os.getenv("REPO_URL", "https://github.com/pratokwau/drebol-vpn.git")


def _run(cmd: list[str], *, cwd: Path | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, cwd=str(cwd or ROOT), capture_output=True, text=True, check=False)


def is_git_repo() -> bool:
    return (ROOT / ".git").exists()


def get_local_head() -> str:
    if not is_git_repo():
        return ""
    res = _run(["git", "rev-parse", "HEAD"])
    return res.stdout.strip() if res.returncode == 0 else ""


def get_remote_head() -> str:
    if not REPO_URL:
        return ""
    res = _run(["git", "ls-remote", REPO_URL, "HEAD"])
    if res.returncode != 0:
        return ""
    first = res.stdout.strip().split()
    return first[0] if first else ""


def update_available() -> bool:
    local = get_local_head()
    remote = get_remote_head()
    return bool(local and remote and local != remote)


def apply_update() -> tuple[bool, str]:
    if not is_git_repo():
        return False, "Папка проекта не является git-репозиторием."

    fetch = _run(["git", "fetch", "--all", "--prune"])
    if fetch.returncode != 0:
        return False, fetch.stderr.strip() or fetch.stdout.strip() or "git fetch failed"

    pull = _run(["git", "pull", "--ff-only"])
    if pull.returncode != 0:
        return False, pull.stderr.strip() or pull.stdout.strip() or "git pull failed"

    pip = _run([str(ROOT / ".venv" / "bin" / "python"), "-m", "pip", "install", "-r", "requirements.txt"])
    if pip.returncode != 0:
        return False, pip.stderr.strip() or pip.stdout.strip() or "pip install failed"

    return True, "Обновление установлено."


def request_restart() -> None:
    raise SystemExit(0)
