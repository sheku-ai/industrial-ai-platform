from __future__ import annotations

import os
import secrets
import string
from contextlib import AbstractContextManager
from typing import Mapping


_MISSING = object()


def generate_credential(length: int = 40, *, prefix: str = "") -> str:
    if length < 16:
        raise ValueError("credential length must be at least 16")
    alphabet = string.ascii_letters + string.digits
    return prefix + "".join(secrets.choice(alphabet) for _ in range(length))


class EnvironmentScope(AbstractContextManager["EnvironmentScope"]):
    """Temporarily updates process environment and restores it exactly."""

    def __init__(self, values: Mapping[str, str | None] | None = None):
        self._values = dict(values or {})
        self._previous: dict[str, object | str] = {}
        self._entered = False

    def __enter__(self) -> "EnvironmentScope":
        if self._entered:
            raise RuntimeError("EnvironmentScope cannot be entered twice")
        self._entered = True
        for key, value in self._values.items():
            self._previous[key] = os.environ.get(key, _MISSING)
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = str(value)
        return self

    def set(self, key: str, value: str | None) -> None:
        if not self._entered:
            raise RuntimeError("EnvironmentScope must be entered before set")
        if key not in self._previous:
            self._previous[key] = os.environ.get(key, _MISSING)
        if value is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = str(value)

    def ensure_ephemeral(self, key: str, *, length: int = 40, prefix: str = "") -> str:
        current = os.environ.get(key)
        if current:
            return current
        generated = generate_credential(length=length, prefix=prefix)
        self.set(key, generated)
        return generated

    def __exit__(self, exc_type, exc, traceback) -> None:
        for key, previous in self._previous.items():
            if previous is _MISSING:
                os.environ.pop(key, None)
            else:
                os.environ[key] = str(previous)
        self._entered = False
        return None
