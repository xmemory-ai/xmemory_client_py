"""TCP keep-alive socket options for the default httpx transport.

Without ``SO_KEEPALIVE`` the kernel never probes the peer; if the remote
end vanishes silently (FIN dropped during OS sleep/wake, NAT re-route,
ALB idle drop, an unrelated server-side bug), ``recv()`` blocks for the
full request timeout — minutes or longer. Setting keep-alive makes the
kernel detect the dead peer in ~60 s and surface it as a connection
error the caller can convert to ``XmemoryAPIError``.

Notes:
- TCP keep-alive probes are answered by the *kernel*, not the
  application. Long-running but healthy requests (e.g. multi-minute
  writes that involve several LLM calls server-side) are unaffected:
  the remote OS keeps ACKing probes regardless of how busy the app is.
- These options are only applied to the default ``httpx.Client`` /
  ``httpx.AsyncClient`` we create internally. If the caller passes
  their own ``http_client``, we don't touch it — their transport is
  their choice.
"""

from __future__ import annotations

import socket
import sys

_KEEPALIVE_IDLE_SECONDS = 30
_KEEPALIVE_INTERVAL_SECONDS = 10
_KEEPALIVE_PROBE_COUNT = 3

_SocketOption = tuple[int, int, int]


def keepalive_socket_options() -> list[_SocketOption]:
    """Return ``socket_options`` to pass to ``httpx.HTTPTransport``.

    Best-effort across platforms:
    - Linux:  SO_KEEPALIVE + TCP_KEEPIDLE + TCP_KEEPINTVL + TCP_KEEPCNT
    - macOS:  SO_KEEPALIVE + TCP_KEEPALIVE (idle, different name from
              Linux's TCP_KEEPIDLE) + TCP_KEEPINTVL + TCP_KEEPCNT
    - Windows / others: just ``SO_KEEPALIVE`` (httpx ``socket_options``
              can't call ioctl, so Windows uses platform-default timers
              of ~2 hours; the application-level timeout still bounds
              waits in the meantime)
    - Anything missing is silently dropped: bad option tuples raise
      OSError on setsockopt; we must not pass them at all.
    """
    options: list[_SocketOption] = [(socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1)]

    if sys.platform == "darwin":
        idle_opt: int | None = getattr(socket, "TCP_KEEPALIVE", 0x10)
    elif sys.platform == "win32":
        # Windows controls keep-alive timers via SIO_KEEPALIVE_VALS ioctl,
        # not via socket options. httpx.HTTPTransport only takes setsockopt-
        # style tuples, so we can't tune the timers here. Leave SO_KEEPALIVE
        # on with system defaults.
        return options
    else:
        idle_opt = getattr(socket, "TCP_KEEPIDLE", None)

    intvl_opt = getattr(socket, "TCP_KEEPINTVL", None)
    cnt_opt = getattr(socket, "TCP_KEEPCNT", None)

    if idle_opt is not None:
        options.append((socket.IPPROTO_TCP, idle_opt, _KEEPALIVE_IDLE_SECONDS))
    if intvl_opt is not None:
        options.append((socket.IPPROTO_TCP, intvl_opt, _KEEPALIVE_INTERVAL_SECONDS))
    if cnt_opt is not None:
        options.append((socket.IPPROTO_TCP, cnt_opt, _KEEPALIVE_PROBE_COUNT))

    return options