"""Chrome Native Messaging host for Browser MCP (portless extension mode).

This process is launched by Chrome when the extension calls `connectNative()`.

It acts as a local broker:
- Extension <-> native host: Chrome Native Messaging (stdin/stdout framing)
- Browser MCP server <-> native host: local IPC (Unix domain socket; no TCP ports)
"""

from __future__ import annotations

import asyncio

from .native_broker import NativeBroker


def main() -> None:
    # Native messaging requires strict stdout framing. Never write logs to stdout.
    try:
        raise SystemExit(asyncio.run(NativeBroker().run()))
    except KeyboardInterrupt:
        raise SystemExit(0) from None


if __name__ == "__main__":
    main()
