"""Vocabulary shared by all operations.

An operation is a list of steps. Each step inspects a repo and returns the
changes needed to bring it in line, so that an empty list means it's in sync.
"""

import dataclasses
from collections.abc import Callable
from typing import Literal

import pydantic


class CannotPlan(Exception):
    """The repo is in a state we don't know how to bring in line."""


class Repository(pydantic.BaseModel):
    id: int
    full_name: str
    default_branch: str
    private: bool


@dataclasses.dataclass(frozen=True, kw_only=True)
class ApiCall:
    method: Literal["POST", "PUT", "PATCH", "DELETE"]
    path: str
    body: pydantic.JsonValue = None

    def __str__(self) -> str:
        return f"{self.method} {self.path}"


@dataclasses.dataclass(frozen=True, kw_only=True)
class SetSecret:
    """PUT an Actions secret, encrypted with the key from public_key_path.

    Encrypting only when applying means the key needn't exist when planning,
    e.g. if it belongs to an environment that an earlier change creates.
    """

    path: str
    public_key_path: str
    value: pydantic.SecretStr

    def __str__(self) -> str:
        return f"PUT {self.path}"


@dataclasses.dataclass(frozen=True, kw_only=True)
class ManualStep:
    """Something we can't (or would rather not) do via the API."""

    instruction: str

    def __str__(self) -> str:
        return self.instruction


@dataclasses.dataclass(frozen=True, kw_only=True)
class Change:
    description: str
    detail: str = ""
    action: ApiCall | SetSecret | ManualStep


type Step = Callable[[Repository], list[Change]]
