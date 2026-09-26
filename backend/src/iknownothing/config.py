import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Settings:
    data_dir: Path
    model_large: str
    model_small: str
    user: str | None
    frontend_dir: Path | None = None

    @classmethod
    def from_env(cls) -> "Settings":
        return cls(
            data_dir=Path(os.environ.get("IKN_DATA_DIR", "data")),
            model_large=os.environ.get("IKN_MODEL_LARGE", "claude-opus-5"),
            model_small=os.environ.get("IKN_MODEL_SMALL", "claude-sonnet-5"),
            user=os.environ.get("IKN_USER"),
            frontend_dir=Path(os.environ["IKN_FRONTEND_DIR"]) if os.environ.get("IKN_FRONTEND_DIR") else None,
        )
