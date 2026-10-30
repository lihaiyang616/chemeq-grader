"""Application configuration and local data layout.

Everything lives under a single user-writable directory so the teacher can back
it up, move it or delete it.  The default is ``%LOCALAPPDATA%\\ChemEq`` on
Windows and ``~/.chemeq`` elsewhere; ``CHEMEQ_HOME`` overrides it (useful for
tests and portable installs).
"""

from __future__ import annotations

import json
import os
import secrets
from contextlib import suppress
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

APP_NAME = "ChemEq"
CONFIG_FILE = "config.json"


def resolve_home(home: Path | str | None = None) -> Path:
    if home is not None:
        return Path(home).expanduser().resolve()
    env = os.environ.get("CHEMEQ_HOME")
    if env:
        return Path(env).expanduser().resolve()
    if os.name == "nt":
        base = os.environ.get("LOCALAPPDATA")
        if base:
            return Path(base) / APP_NAME
        return Path.home() / "AppData" / "Local" / APP_NAME
    return Path.home() / ".chemeq"


@dataclass
class Config:
    home: Path
    data_dir: Path
    db_path: Path
    uploads_dir: Path
    reports_dir: Path
    logs_dir: Path
    config_path: Path
    host: str = "0.0.0.0"
    port: int = 8765
    api_key: str = ""
    base_url: str = "https://api.deepseek.com"
    model: str = "deepseek-flash"
    max_tokens: int = 3000
    temperature: float = 0.1
    timeout_seconds: int = 120
    max_concurrency: int = 3
    budget_cny: float = 5.0
    max_upload_mb: int = 20
    max_batch: int = 120
    max_pages: int = 10
    strict_scoring: bool = True
    admin_token: str = ""
    mobile_token: str = ""
    consent: bool = False
    extra: dict[str, Any] = field(default_factory=dict)

    def save(self) -> None:
        self.data_dir.mkdir(parents=True, exist_ok=True)
        payload = self.to_dict()
        tmp = self.config_path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(self.config_path)
        with suppress(OSError):
            os.chmod(self.config_path, 0o600)

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        for key in ("home", "data_dir", "db_path", "uploads_dir", "reports_dir", "logs_dir", "config_path"):
            payload[key] = str(payload[key])
        return payload

    def public_dict(self) -> dict[str, Any]:
        payload = self.to_dict()
        if payload.get("api_key"):
            payload["api_key"] = mask_secret(payload["api_key"])
        payload["has_api_key"] = bool(self.api_key)
        return payload

    @property
    def masked_api_key(self) -> str:
        return mask_secret(self.api_key)


def mask_secret(value: str) -> str:
    if not value:
        return ""
    if len(value) <= 8:
        return "***"
    return value[:4] + "***" + value[-4:]


def _defaults(home: Path) -> Config:
    data_dir = home / "data"
    return Config(
        home=home,
        data_dir=data_dir,
        db_path=data_dir / "chemeq.db",
        uploads_dir=data_dir / "uploads",
        reports_dir=data_dir / "reports",
        logs_dir=data_dir / "logs",
        config_path=home / CONFIG_FILE,
    )


def load_config(home: Path | str | None = None) -> Config:
    resolved = resolve_home(home)
    cfg = _defaults(resolved)
    resolved.mkdir(parents=True, exist_ok=True)

    if cfg.config_path.exists():
        try:
            payload = json.loads(cfg.config_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            payload = {}
        path_fields = {"home", "data_dir", "db_path", "uploads_dir", "reports_dir", "logs_dir", "config_path"}
        for key, value in payload.items():
            if key in path_fields:
                continue
            if hasattr(cfg, key):
                setattr(cfg, key, value)

    # Environment overrides are useful for CI and for a teacher who keeps the
    # key outside config.json.
    env_map = {
        "CHEMEQ_API_KEY": "api_key",
        "CHEMEQ_BASE_URL": "base_url",
        "CHEMEQ_MODEL": "model",
        "CHEMEQ_HOST": "host",
        "CHEMEQ_PORT": "port",
    }
    for env_key, field_name in env_map.items():
        value = os.environ.get(env_key)
        if value:
            if field_name == "port":
                try:
                    value = int(value)  # type: ignore[assignment]
                except ValueError:
                    continue
            setattr(cfg, field_name, value)

    if not cfg.admin_token:
        cfg.admin_token = secrets.token_urlsafe(18)
    if not cfg.mobile_token:
        cfg.mobile_token = secrets.token_urlsafe(18)

    for directory in (cfg.data_dir, cfg.uploads_dir, cfg.reports_dir, cfg.logs_dir):
        directory.mkdir(parents=True, exist_ok=True)

    cfg.save()
    return cfg


def mobile_url_base(cfg: Config, lan_ip: str) -> str:
    return f"http://{lan_ip}:{cfg.port}/m/{cfg.mobile_token}"


def admin_url(cfg: Config) -> str:
    return f"http://127.0.0.1:{cfg.port}"
