#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Generate doc/STATUS.md with current repo status:
- Version (latest tag) and current commit
- Docker base image
- Services from docker-compose.yml
- DB runtime mode hint (PostgreSQL present, DATABASE_URL set/unset)
- Explicit flag: project mode is PostgreSQL only
- Top dependencies from requirements.txt

Usage:
  python3 scripts/docs/generate_status.py

This script does not print or store any secret values. It only writes
boolean facts (e.g., DATABASE_URL set/unset) and public metadata.
"""
from __future__ import annotations

import os
import re
import subprocess
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DOC = ROOT / "doc" / "STATUS.md"


def _run(cmd: list[str]) -> str:
    try:
        out = subprocess.check_output(cmd, cwd=str(ROOT))
        return out.decode("utf-8", errors="replace").strip()
    except Exception:
        return ""


def latest_tag() -> str:
    tag = _run(["git", "--no-pager", "describe", "--tags", "--abbrev=0"]) or ""
    return tag or "(no tag)"


def short_sha() -> str:
    sha = _run(["git", "--no-pager", "rev-parse", "--short", "HEAD"]) or ""
    return sha or "(unknown)"


def docker_base() -> str:
    dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8", errors="ignore") if (ROOT / "Dockerfile").exists() else ""
    m = re.search(r"^FROM\s+([^\s]+)\s*$", dockerfile, flags=re.MULTILINE)
    return m.group(1) if m else "(unknown)"


def compose_services() -> list[str]:
    path = ROOT / "docker-compose.yml"
    if not path.exists():
        return []
    lines = path.read_text(encoding="utf-8", errors="ignore").splitlines()
    services: list[str] = []
    in_services = False
    for line in lines:
        if re.match(r"^services:\s*$", line):
            in_services = True
            continue
        if in_services:
            m = re.match(r"^\s{2}([a-zA-Z0-9_-]+):\s*$", line)
            if m:
                services.append(m.group(1))
            # end of services block if dedented to column 0 and not empty
            if line and not line.startswith(" "):
                break
    return services


def database_state() -> tuple[str, bool]:
    # Runtime hint based on presence of postgres service and DATABASE_URL existence in .env
    services = compose_services()
    has_pg = "postgres" in services
    env_path = ROOT / ".env"
    db_url_set = False
    if env_path.exists():
        try:
            txt = env_path.read_text(encoding="utf-8", errors="ignore")
            m = re.search(r"^\s*DATABASE_URL\s*=\s*(.+)$", txt, flags=re.MULTILINE)
            if m and m.group(1).strip():
                db_url_set = True
        except Exception:
            pass
    return ("PostgreSQL" if has_pg else "SQLite"), db_url_set


def read_requirements(limit: int = 12) -> list[str]:
    req = ROOT / "requirements.txt"
    if not req.exists():
        return []
    libs: list[str] = []
    for line in req.read_text(encoding="utf-8", errors="ignore").splitlines():
        s = line.strip()
        if not s or s.startswith("#"):
            continue
        libs.append(s)
        if len(libs) >= limit:
            break
    return libs


def main() -> None:
    now = datetime.now(timezone.utc).astimezone().isoformat()
    tag = latest_tag()
    sha = short_sha()
    base = docker_base()
    services = compose_services()
    db_mode, dburl = database_state()
    reqs = read_requirements()

    md = []
    md.append("# STATUS — текущее состояние проекта")
    md.append("")
    md.append(f"Обновлено: {now}")
    md.append("")
    md.append("## Версия и сборка")
    md.append(f"- Последний тег: {tag}")
    md.append(f"- Текущий коммит: {sha}")
    md.append(f"- Docker base image: {base}")
    md.append("")
    md.append("## Сервисы (docker-compose)")
    if services:
        for s in services:
            md.append(f"- {s}")
    else:
        md.append("- (не обнаружены)")
    md.append("")
    md.append("## База данных")
    md.append(f"- Режим рантайма (по compose): {db_mode}")
    md.append(f"- DATABASE_URL в .env: {'установлена' if dburl else 'не установлена'} (значение не показывается)")
    md.append(f"- Режим проекта: PostgreSQL only")
    md.append("")
    md.append("## Ключевые зависимости (requirements.txt)")
    if reqs:
        for r in reqs:
            md.append(f"- {r}")
    else:
        md.append("- (нет данных)")
    md.append("")
    md.append("---")
    md.append("Этот файл сгенерирован скриптом `scripts/docs/generate_status.py`. Не редактируйте вручную.")

    DOC.parent.mkdir(parents=True, exist_ok=True)
    DOC.write_text("\n".join(md) + "\n", encoding="utf-8")
    print(f"Wrote {DOC}")


if __name__ == "__main__":
    main()
