import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Settings:
    data_dir: Path
    model_large: str
    model_small: str
    frontend_dir: Path | None = None
    courses_dir: Path = Path("courses")

    @classmethod
    def from_env(cls) -> "Settings":
        return cls(
            data_dir=Path(os.environ.get("IKN_DATA_DIR", "data")),
            model_large=os.environ.get("IKN_MODEL_LARGE", "claude-opus-5"),
            model_small=os.environ.get("IKN_MODEL_SMALL", "claude-sonnet-5"),
            frontend_dir=Path(os.environ["IKN_FRONTEND_DIR"]) if os.environ.get("IKN_FRONTEND_DIR") else None,
            courses_dir=Path(os.environ.get("IKN_COURSES_DIR", "courses")),
        )
