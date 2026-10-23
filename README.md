# Distributed Client-Server App

Scaffold for a collaborative client-server application with:

- TCP/TLS authenticated application traffic
- UDP peer discovery and heartbeats
- scrypt-based password derivation
- framed protocol messages
- chunked file transfer with checksums

## Development

Copy `.env.example` to `.env`, provide local certificates as described in
`certs/README.md`, and install the package with your preferred Python
environment.

Runtime files belong in `data/` and are intentionally excluded from Git.
