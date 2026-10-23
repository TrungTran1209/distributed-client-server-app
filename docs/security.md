# Security

- Never commit private keys, passwords, or runtime account data.
- Use TLS for TCP application traffic.
- Store passwords as salted scrypt-derived hashes; never store plaintext
  passwords.
- Validate message schemas and file-transfer checksums at trust boundaries.
