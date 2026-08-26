"""
Command execution abstraction.

Replaces any fixed notion of a "bastion": a tenant chooses, in its config,
where its commands run — locally on the backend's machine, or remotely via
SSH to a configured host. The rest of the code (kubectl/az/etc. tools, and
future ones) only ever talks to this interface, never a direct subprocess.
See docs/execution-model.md.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass
class ExecResult:
    stdout: str
    stderr: str
    returncode: int
    command: str
    error: str | None = None

    @property
    def ok(self) -> bool:
        return self.error is None and self.returncode == 0


class CommandExecutor(ABC):
    @abstractmethod
    async def run(
        self,
        command: list[str] | str,
        *,
        env: dict[str, str] | None = None,
        timeout: int = 30,
        shell: bool = False,
    ) -> ExecResult:
        """
        Runs a command and returns its result.

        `shell=True` allows pipes/redirections but requires `command: str`;
        `shell=False` (default) expects a list of arguments (no shell interpretation).
        """
        raise NotImplementedError
