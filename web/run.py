"""Shared helpers for starting the local API server."""

from __future__ import annotations

import socket
import sys
import time
import urllib.error
import urllib.request


def port_available(port: int, host: str = "127.0.0.1") -> bool:
    """Return whether *port* can be bound on *host*."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        if sys.platform == "win32":
            # SO_REUSEADDR on Windows lets a bind succeed on top of a live listener, so a stray
            # server would look like a free port. Ask for exclusive use instead.
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        else:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            sock.bind((host, port))
            return True
        except OSError:
            return False


def require_port(port: int, host: str = "127.0.0.1") -> int:
    """Return *port* or raise if it is already in use."""
    if port_available(port, host):
        return port
    raise SystemExit(
        f"Port {port} is already in use on {host}.\n"
        "Another Toolbox server is probably still running with older code.\n"
        "Stop that process, then start the server again.\n"
        "On Windows: netstat -ano | findstr :{port}  then  taskkill /PID <pid> /F"
    )


def pick_port(preferred: int, host: str = "127.0.0.1") -> int:
    """Return *preferred* if bindable, otherwise an ephemeral port on *host*."""
    if port_available(preferred, host):
        return preferred
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.bind((host, 0))
        return sock.getsockname()[1]


def wait_for_server(base_url: str, timeout: float = 30.0) -> None:
    """Poll ``/api/health`` until the server responds or *timeout* expires."""
    health_url = f"{base_url.rstrip('/')}/api/health"
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(health_url, timeout=1) as resp:
                if resp.status == 200:
                    return
        except (urllib.error.URLError, TimeoutError, OSError):
            time.sleep(0.1)
    raise RuntimeError(f"Server did not become ready within {timeout:.0f}s ({health_url})")


def run_uvicorn(host: str, port: int, *, log_level: str = "info") -> None:
    import uvicorn

    uvicorn.run(
        "web.server:app",
        host=host,
        port=port,
        log_level=log_level,
    )
