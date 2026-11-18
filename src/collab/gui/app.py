"""Desktop bootstrap: launches LumiChat Client by default, or Server Console with `--server`."""

from __future__ import annotations

import sys


def main() -> None:  # pragma: no cover - requires display
    if "--server" in sys.argv:
        sys.argv = [arg for arg in sys.argv if arg != "--server"]
        from .server_app import main as server_main

        server_main()
        return
    from .client_app import main as client_main

    client_main()
