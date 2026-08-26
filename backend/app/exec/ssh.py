"""
Runs commands remotely over SSH, on the host configured for the tenant
(`exec.ssh` in tenants.yaml). This is *not* a "bastion" concept — just a
remote machine reachable via SSH, like any other. See
docs/execution-model.md.
"""
from __future__ import annotations

import asyncio
import logging
import os
import shlex

import asyncssh

from app.config.schema import SSHExecConfig
from app.exec.base import CommandExecutor, ExecResult

logger = logging.getLogger("aegis.exec.ssh")


class SSHExecutor(CommandExecutor):
    def __init__(self, config: SSHExecConfig):
        self._config = config
        self._conn: asyncssh.SSHClientConnection | None = None
        self._connect_lock = asyncio.Lock()

    async def _connection(self) -> asyncssh.SSHClientConnection:
        async with self._connect_lock:
            if self._conn is None or self._conn.is_closed():
                known_hosts = self._config.known_hosts_path
                if known_hosts:
                    known_hosts = os.path.expanduser(known_hosts)
                else:
                    # No known_hosts provided → verification disabled.
                    # Acceptable for a host the operator configures
                    # themselves on a trusted network, but it's a real MITM
                    # risk on an untrusted one — see docs/execution-model.md.
                    # Logged explicitly (once per connection, not per
                    # command) rather than silently.
                    logger.warning(
                        "SSHExecutor to %s: known_hosts_path not set, host "
                        "key verification disabled.",
                        self._config.host,
                    )
                connect_kwargs: dict = {}
                if self._config.certificate_path:
                    # Certificate-based auth (e.g. Azure AD `az ssh config`,
                    # Vault SSH secrets engine): client_certs is paired
                    # positionally with client_keys by asyncssh.
                    connect_kwargs["client_certs"] = [os.path.expanduser(self._config.certificate_path)]
                self._conn = await asyncssh.connect(
                    self._config.host,
                    port=self._config.port,
                    username=self._config.user,
                    client_keys=[os.path.expanduser(self._config.key_path)],
                    known_hosts=known_hosts,
                    **connect_kwargs,
                )
            return self._conn

    async def run(
        self,
        command: list[str] | str,
        *,
        env: dict[str, str] | None = None,
        timeout: int = 30,
        shell: bool = False,
    ) -> ExecResult:
        # SSH always runs through the remote shell — `shell` doesn't change
        # anything here, it just documents the caller's intent (consistency
        # with LocalExecutor).
        if isinstance(command, list):
            cmd_str = " ".join(shlex.quote(part) for part in command)
        else:
            cmd_str = command

        try:
            conn = await self._connection()
        except (OSError, asyncssh.Error) as e:
            return ExecResult(stdout="", stderr="", returncode=-1, command=cmd_str, error=f"SSH connect: {e}")

        try:
            result = await asyncio.wait_for(
                conn.run(cmd_str, env=env, check=False), timeout=timeout
            )
        except asyncio.TimeoutError:
            return ExecResult(
                stdout="", stderr="", returncode=-1, command=cmd_str,
                error=f"Timeout ({timeout}s)",
            )
        except asyncssh.Error as e:
            return ExecResult(stdout="", stderr="", returncode=-1, command=cmd_str, error=str(e))

        return ExecResult(
            stdout=str(result.stdout or ""),
            stderr=str(result.stderr or ""),
            returncode=result.exit_status or 0,
            command=cmd_str,
        )

    async def close(self) -> None:
        if self._conn is not None:
            self._conn.close()
            await self._conn.wait_closed()
            self._conn = None
