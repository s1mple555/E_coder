import os
import tempfile
from dataclasses import dataclass, replace
from pathlib import Path

from dotenv import dotenv_values, set_key

ROOT = Path(__file__).resolve().parent.parent


@dataclass
class Settings:
    root: Path
    workspace: Path
    mode: str = "live"
    api_key: str = ""
    base_url: str = "https://api.stepfun.com/step_plan/v1"
    model: str = "step-5-preview"
    max_steps: int = 40
    context_chars: int = 60000
    goal_block_cap: int = 8
    permission_mode: str = "approval"

    @classmethod
    def load(cls):
        values = {**os.environ, **{k: v for k, v in dotenv_values(ROOT / ".env").items() if v is not None}}
        workspace = Path(values.get("ECODER_WORKSPACE", "workspace"))
        return cls(
            root=ROOT,
            workspace=(ROOT / workspace).resolve(),
            mode="live",
            permission_mode="full" if values.get("ECODER_PERMISSION_MODE") == "full" else "approval",
            api_key=values.get("ECODER_API_KEY", ""),
            base_url=values.get("ECODER_BASE_URL", "https://api.stepfun.com/step_plan/v1").rstrip("/"),
            model=values.get("ECODER_MODEL", "step-5-preview"),
            max_steps=max(1, min(64, int(values.get("ECODER_MAX_STEPS", "40")))),
            context_chars=max(12000, int(values.get("ECODER_CONTEXT_CHARS", "60000"))),
            goal_block_cap=max(1,min(100,int(values.get('ECODER_GOAL_BLOCK_CAP','8')))),
        )


def save_model_settings(settings, *, base_url, model, api_key=None, permission_mode=None):
    """Persist all model fields atomically before replacing runtime settings.

    None means keep the existing key. Preserve unrelated .env fields/comments.
    Never log arguments or return the credential to an HTTP client.
    """
    if permission_mode not in {None, "approval", "full"}:
        raise ValueError("未知权限模式")
    updated = replace(settings, permission_mode=permission_mode or settings.permission_mode, base_url=base_url, model=model,
                      api_key=settings.api_key if api_key is None else api_key)
    destination = settings.root / ".env"
    if destination.is_symlink():
        raise OSError("Configuration file must not be a symbolic link")
    with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=settings.root,
                                     prefix=".ecoder-config-", suffix=".tmp", delete=False) as handle:
        temporary = Path(handle.name)
    try:
        temporary.write_text(destination.read_text(encoding="utf-8") if destination.exists() else "", encoding="utf-8")
        for name, value in {"ECODER_API_KEY": updated.api_key, "ECODER_BASE_URL": updated.base_url, "ECODER_MODEL": updated.model, "ECODER_PERMISSION_MODE": updated.permission_mode}.items():
            set_key(temporary, name, value, quote_mode="always")
        os.replace(temporary, destination)
    finally:
        temporary.unlink(missing_ok=True)
    return updated
