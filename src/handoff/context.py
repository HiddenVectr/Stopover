"""Who is making a request. Every service and backend operation is scoped by one."""
from __future__ import annotations

from dataclasses import dataclass

LOCAL_WORKSPACE = "local"


@dataclass(frozen=True)
class RequestContext:
    workspace: str = LOCAL_WORKSPACE
    actor: str | None = None  # Authenticated principal, recorded in event history when known.


LOCAL = RequestContext()
