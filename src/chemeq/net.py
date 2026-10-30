"""Small network helpers shared by the CLI and the web UI."""

from __future__ import annotations

import socket


def lan_ip() -> str:
    """Best-effort LAN IPv4 address of this machine."""

    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.connect(("8.8.8.8", 80))
            address = sock.getsockname()[0]
            if address and not address.startswith("127."):
                return address
    except OSError:
        pass
    try:
        address = socket.gethostbyname(socket.gethostname())
        if address and not address.startswith("127."):
            return address
    except OSError:
        pass
    return "127.0.0.1"


def port_available(port: int, host: str = "0.0.0.0") -> bool:
    # A process may be bound specifically to 127.0.0.1 while 0.0.0.0 still
    # accepts a bind on some Windows configurations.  Try a connect first.
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.settimeout(0.25)
        if probe.connect_ex(("127.0.0.1", int(port))) == 0:
            return False
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            sock.bind((host, int(port)))
            return True
        except OSError:
            return False
