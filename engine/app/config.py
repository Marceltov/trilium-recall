"""Configuration from environment variables (no CLI args, so it runs cleanly as a sidecar)."""

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path


class ConfigError(Exception):
    pass


@dataclass(frozen=True)
class InstanceConfig:
    name: str
    url: str  # ETAPI base, always ending in /etapi
    etapi_token: str


@dataclass
class Config:
    token: str
    instances: list[InstanceConfig]
    data_dir: Path = Path("/data")
    model_dir: Path = Path("/models/e5-small")
    host: str = "0.0.0.0"
    port: int = 8082
    poll_seconds: int = 60
    reconcile_seconds: int = 1800
    log_level: str = "INFO"


def _env_name(instance: str) -> str:
    return instance.upper().replace("-", "_")


def _etapi_url(url: str) -> str:
    url = url.rstrip("/")
    return url if url.endswith("/etapi") else url + "/etapi"


def _int(env: Mapping[str, str], key: str, default: int) -> int:
    raw = env.get(key)
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError:
        raise ConfigError(f"{key} must be an integer, got {raw!r}") from None


def load_config(env: Mapping[str, str]) -> Config:
    token = env.get("RECALL_TOKEN", "").strip()
    if not token:
        raise ConfigError("RECALL_TOKEN is not set: clients authenticate with it, so the engine refuses to start without it")
    names = [n.strip() for n in env.get("RECALL_INSTANCES", "").split(",") if n.strip()]
    if not names:
        raise ConfigError("RECALL_INSTANCES is empty: name at least one Trilium instance, e.g. RECALL_INSTANCES=marcel")
    instances = []
    for name in names:
        prefix = f"TRILIUM_{_env_name(name)}"
        url = env.get(f"{prefix}_URL", "").strip()
        etapi = env.get(f"{prefix}_TOKEN", "").strip()
        if not url:
            raise ConfigError(f"{prefix}_URL is not set for instance {name!r}")
        if not etapi:
            raise ConfigError(f"{prefix}_TOKEN is not set for instance {name!r}")
        instances.append(InstanceConfig(name, _etapi_url(url), etapi))
    return Config(
        token=token,
        instances=instances,
        data_dir=Path(env.get("RECALL_DATA_DIR", "/data")),
        model_dir=Path(env.get("RECALL_MODEL_DIR", "/models/e5-small")),
        host=env.get("RECALL_HOST", "0.0.0.0"),
        port=_int(env, "RECALL_PORT", 8082),
        poll_seconds=_int(env, "RECALL_POLL_SECONDS", 60),
        reconcile_seconds=_int(env, "RECALL_RECONCILE_SECONDS", 1800),
        log_level=env.get("RECALL_LOG_LEVEL", "INFO"),
    )
