"""Users: the directories under data/."""

import re
import shutil
from pathlib import Path

_NAME = re.compile(r"^[a-z0-9][a-z0-9_-]*$")


class AccountError(Exception):
    pass


def check_name(name: str) -> None:
    if not _NAME.match(name):
        raise AccountError(f"invalid name: {name!r}; use lowercase letters, digits, - and _")


def names(data_dir: Path) -> list[str]:
    if not data_dir.is_dir():
        return []
    return sorted(p.name for p in data_dir.iterdir() if p.is_dir() and _NAME.match(p.name))


def exists(data_dir: Path, name: str) -> bool:
    return bool(_NAME.match(name)) and (data_dir / name).is_dir()


def add(data_dir: Path, name: str) -> None:
    check_name(name)
    if exists(data_dir, name):
        raise AccountError(f"user exists: {name}")
    (data_dir / name).mkdir(parents=True)


def remove(data_dir: Path, name: str) -> None:
    """Deletes the user with all their courses."""
    if not exists(data_dir, name):
        raise AccountError(f"no such user: {name}")
    shutil.rmtree(data_dir / name)
