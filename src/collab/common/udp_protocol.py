"""Schemas for UDP discovery and heartbeat messages."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class DiscoveryMessage:
    """A peer discovery or heartbeat announcement."""

    node_id: str
    host: str
    port: int
    kind: str = "heartbeat"
