# Certificates

Place local development certificates in this directory. Private keys are
intentionally ignored by Git and must never be committed.

For development, create a local certificate authority and a server
certificate whose SAN includes the configured host. Configure the resulting
paths through `.env`; use a trusted certificate authority in production.
