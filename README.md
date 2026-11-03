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

Start the TLS server from the repository root after placing the server
certificate/key and trusting its CA on clients:

```powershell
python -m collab.server.main --cert certs/server.crt --key certs/server.key
```

The server listens on TCP `37021` and UDP discovery `37020` by default. Set
`COLLAB_ADVERTISE_HOST` to the LAN address clients can reach when automatic
address selection is unsuitable. Runtime options are also available as
`--host`, `--port`, `--udp-port`, `--database`, and `--advertise-host`.
The account database is created at `data/users.sqlite3`; passwords are stored
as per-account scrypt hashes. Do not commit certificates/private keys or the
runtime database.

Runtime files belong in `data/` and are intentionally excluded from Git.
