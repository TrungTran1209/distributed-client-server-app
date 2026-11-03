"""Helpers for creating TLS contexts and wrapping sockets."""

from __future__ import annotations

import ssl


def create_server_context(cert_file: str, key_file: str) -> ssl.SSLContext:
    """Create a server TLS context using the supplied certificate and key."""
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.minimum_version = ssl.TLSVersion.TLSv1_2
    context.load_cert_chain(certfile=cert_file, keyfile=key_file)
    return context


def create_client_context(ca_file: str | None = None) -> ssl.SSLContext:
    """Create a client TLS context with optional explicit CA trust."""
    context = ssl.create_default_context(cafile=ca_file)
    context.minimum_version = ssl.TLSVersion.TLSv1_2
    return context
