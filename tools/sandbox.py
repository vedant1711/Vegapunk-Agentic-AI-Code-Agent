"""Docker sandbox — safe, isolated code execution environments."""

from __future__ import annotations

import asyncio
import logging
import uuid
from typing import Any

import docker
from docker.errors import DockerException, ContainerError

from app.config import settings

logger = logging.getLogger(__name__)


class DockerSandbox:
    """Manages Docker containers for safe, isolated code execution.

    Each task gets its own container with:
    - Resource limits (CPU, memory)
    - Network isolation
    - Automatic cleanup
    """

    def __init__(self) -> None:
        try:
            self._docker = docker.from_env()
            self._available = True
            logger.info("Docker sandbox initialized successfully.")
        except DockerException as e:
            logger.warning(f"Docker not available — sandbox disabled: {e}")
            self._available = False
            self._docker = None

    @property
    def available(self) -> bool:
        return self._available

    async def execute(
        self,
        command: str,
        working_dir: str,
        timeout: int | None = None,
        env: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        """Execute a command inside a sandboxed Docker container.

        Args:
            command: Shell command to execute.
            working_dir: Host directory to mount as /workspace in the container.
            timeout: Execution timeout in seconds (defaults to settings.sandbox_timeout).
            env: Optional environment variables for the container.

        Returns:
            Dict with 'stdout', 'stderr', 'exit_code'.
        """
        if not self._available:
            # Fallback: run locally (for development only)
            return await self._local_execute(command, working_dir, timeout)

        timeout = timeout or settings.sandbox_timeout
        container_name = f"sandbox-{uuid.uuid4().hex[:8]}"

        try:
            container = await asyncio.to_thread(
                self._docker.containers.run,
                image=settings.sandbox_image,
                command=f"bash -c '{command}'",
                working_dir="/workspace",
                volumes={working_dir: {"bind": "/workspace", "mode": "rw"}},
                name=container_name,
                mem_limit=settings.sandbox_memory_limit,
                cpu_period=100000,
                cpu_quota=int(settings.sandbox_cpu_limit * 100000),
                network_mode="none",  # No network access inside sandbox
                environment=env or {},
                detach=True,
                remove=False,
            )

            # Wait for completion with timeout
            result = await asyncio.to_thread(container.wait, timeout=timeout)
            exit_code = result.get("StatusCode", -1)

            # Capture logs
            stdout = await asyncio.to_thread(
                container.logs, stdout=True, stderr=False
            )
            stderr = await asyncio.to_thread(
                container.logs, stdout=False, stderr=True
            )

            logger.info(
                f"Sandbox {container_name}: exit_code={exit_code}, "
                f"stdout={len(stdout)} bytes, stderr={len(stderr)} bytes"
            )

            return {
                "stdout": stdout.decode("utf-8", errors="replace"),
                "stderr": stderr.decode("utf-8", errors="replace"),
                "exit_code": exit_code,
                "container": container_name,
            }

        except Exception as e:
            logger.error(f"Sandbox execution failed: {e}")
            return {"error": str(e), "exit_code": -1, "stdout": "", "stderr": ""}

        finally:
            # Always cleanup the container
            try:
                container = self._docker.containers.get(container_name)
                await asyncio.to_thread(container.remove, force=True)
            except Exception:
                pass

    async def _local_execute(
        self, command: str, working_dir: str, timeout: int | None
    ) -> dict[str, Any]:
        """Fallback: execute locally when Docker isn't available (dev only).

        ⚠️ NOT sandboxed — use only in development.
        """
        logger.warning("Running command locally (no Docker sandbox)!")
        timeout = timeout or settings.sandbox_timeout

        try:
            proc = await asyncio.create_subprocess_shell(
                command,
                cwd=working_dir,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )

            stdout, stderr = await asyncio.wait_for(
                proc.communicate(), timeout=timeout
            )

            return {
                "stdout": stdout.decode("utf-8", errors="replace"),
                "stderr": stderr.decode("utf-8", errors="replace"),
                "exit_code": proc.returncode or 0,
                "container": "local",
            }

        except asyncio.TimeoutError:
            return {"error": "Execution timed out", "exit_code": -1, "stdout": "", "stderr": ""}
        except Exception as e:
            return {"error": str(e), "exit_code": -1, "stdout": "", "stderr": ""}

    async def build_sandbox_image(self) -> dict[str, Any]:
        """Build the sandbox Docker image from sandbox/Dockerfile.sandbox.

        Should be run once during setup.
        """
        if not self._available:
            return {"error": "Docker not available"}

        try:
            import os
            project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            dockerfile_path = os.path.join(project_root, "sandbox")

            image, build_log = await asyncio.to_thread(
                self._docker.images.build,
                path=dockerfile_path,
                dockerfile="Dockerfile.sandbox",
                tag=settings.sandbox_image,
                rm=True,
            )
            logger.info(f"Built sandbox image: {image.tags}")
            return {"status": "built", "image": settings.sandbox_image}
        except Exception as e:
            return {"error": f"Failed to build sandbox image: {e}"}


# Module-level singleton
sandbox = DockerSandbox()


# Tool definitions for LLM function calling
SANDBOX_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "execute_command",
            "description": "Execute a shell command in a sandboxed Docker container. Use this to run code, install dependencies, or execute tests safely.",
            "parameters": {
                "type": "object",
                "properties": {
                    "command": {"type": "string", "description": "Shell command to execute"},
                    "working_dir": {"type": "string", "description": "Working directory path"},
                },
                "required": ["command", "working_dir"],
            },
        },
    },
]
