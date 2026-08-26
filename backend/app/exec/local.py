"""
Runs commands as a local subprocess, on the machine where the backend runs.
Default executor — fits when the backend already has direct network access
to the infra it controls.
"""
from __future__ import annotations

import asyncio

from app.exec.base import CommandExecutor, ExecResult


class LocalExecutor(CommandExecutor):
    async def run(
        self,
        command: list[str] | str,
        *,
        env: dict[str, str] | None = None,
        timeout: int = 30,
        shell: bool = False,
    ) -> ExecResult:
        display_cmd = command if isinstance(command, str) else " ".join(command)

        try:
            if shell:
                if not isinstance(command, str):
                    raise TypeError("shell=True requires a str command")
                proc = await asyncio.create_subprocess_shell(
                    command,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                    env=env,
                )
            else:
                if not isinstance(command, list):
                    raise TypeError("shell=False requires a list of arguments")
                proc = await asyncio.create_subprocess_exec(
                    *command,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                    env=env,
                )
        except FileNotFoundError as e:
            return ExecResult(stdout="", stderr="", returncode=-1, command=display_cmd, error=str(e))

        try:
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        except asyncio.TimeoutError:
            proc.kill()
            await proc.wait()
            return ExecResult(
                stdout="", stderr="", returncode=-1, command=display_cmd,
                error=f"Timeout ({timeout}s)",
            )

        return ExecResult(
            stdout=stdout.decode(errors="replace"),
            stderr=stderr.decode(errors="replace"),
            returncode=proc.returncode or 0,
            command=display_cmd,
        )
