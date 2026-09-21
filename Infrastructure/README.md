# Infrastructure

Optional environment-facing backends. Local storage and localhost networking
are the defaults. Nothing in this directory is required for a local-only
EverSpark session.

## Storage

`Storage/rclone.sh` preserves the verified rclone abstraction from the WebUI
branch. Image Forge and Concept Forge own their remote paths and transfer
policies; Infrastructure only provides connection and transfer primitives.

R2 is enabled by selecting an rclone-backed storage mode and supplying an
existing rclone configuration. Missing or invalid remote configuration is a
startup error after the backend has been explicitly enabled.

## Network

`Network/Tunnel` implements the existing Cloudflare Named Tunnel flow using a
tunnel UUID, hostname, local port, and credential JSON. The scripts exit
successfully without starting cloudflared while
`EVERSPARK_NETWORK_BACKEND=local`.
