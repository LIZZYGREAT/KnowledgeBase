# Deployment

The current `docker-compose.yml` is a local development skeleton. It binds services to localhost and does not publish the Reference Hub or API to the public internet.

The production deployment profile, persistent backups, secret handling, and Tailscale / WireGuard access belong to Phase 12. API keys must be supplied to the backend environment and must never be stored in canonical knowledge or committed files.
