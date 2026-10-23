# Architecture

The application is split into common protocol/security utilities, a
concurrent TCP/TLS server, a CLI client, and file-transfer components.
Discovery and heartbeats use UDP; authenticated application traffic uses
length-framed messages over TLS.
