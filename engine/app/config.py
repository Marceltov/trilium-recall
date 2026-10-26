"""Configuration from environment variables (no CLI args, so it runs cleanly as a sidecar)."""

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from mcp.server.auth.routes import validate_issuer_url
from pydantic import AnyHttpUrl


class ConfigError(Exception):
    pass


@dataclass(frozen=True)
class InstanceConfig:
    name: str
    url: str  # ETAPI base, always ending in /etapi
    etapi_token: str


DEFAULT_TOOL_DESCRIPTION = (
    "Search the user's Trilium notes (decisions, findings, how their systems and tools actually behave) and "
    "get up to 3 short passages with note IDs. Call it on your own before a task the notes may cover, when you "
    "hit an unfamiliar error, host or service, and before making a decision the notes may already have made. "
    "Returns nothing-relevant when there is no match. Read a full note with the Trilium MCP using the note ID.")


@dataclass
class Config:
    password: str  # RECALL_LOGIN_PASSWORD: a static Bearer token, and the OAuth login page's password
    instances: list[InstanceConfig]
    base_url: str | None = None  # public URL; set, it turns on OAuth for /mcp
    data_dir: Path = Path("/data")
    model_dir: Path = Path("/models/e5-small")
    host: str = "0.0.0.0"
    port: int = 8082
    poll_seconds: int = 60
    reconcile_seconds: int = 1800
    log_level: str = "INFO"
    tool_description: str = DEFAULT_TOOL_DESCRIPTION  # what MCP clients read about the recall tool


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
    if env.get("RECALL_TOKEN", "").strip():
        raise ConfigError("RECALL_TOKEN was renamed to RECALL_LOGIN_PASSWORD in 0.3.0: rename it in the environment")
    password = env.get("RECALL_LOGIN_PASSWORD", "").strip()
    if not password:
        raise ConfigError("RECALL_LOGIN_PASSWORD is not set: clients authenticate with it, "
                          "so the engine refuses to start without it")
    base_url = env.get("RECALL_BASE_URL", "").strip().rstrip("/") or None
    if base_url:
        try:
            validate_issuer_url(AnyHttpUrl(base_url))
        except ValueError as e:
            raise ConfigError(f"RECALL_BASE_URL={base_url!r} is not a valid OAuth issuer "
                              f"(https, no query or fragment; plain http only for localhost): {e}") from None
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
        password=password,
        instances=instances,
        base_url=base_url,
        data_dir=Path(env.get("RECALL_DATA_DIR", "/data")),
        model_dir=Path(env.get("RECALL_MODEL_DIR", "/models/e5-small")),
        host=env.get("RECALL_HOST", "0.0.0.0"),
        port=_int(env, "RECALL_PORT", 8082),
        poll_seconds=_int(env, "RECALL_POLL_SECONDS", 60),
        reconcile_seconds=_int(env, "RECALL_RECONCILE_SECONDS", 1800),
        log_level=env.get("RECALL_LOG_LEVEL", "INFO"),
        tool_description=env.get("RECALL_TOOL_DESCRIPTION", "").strip() or DEFAULT_TOOL_DESCRIPTION,
    )
