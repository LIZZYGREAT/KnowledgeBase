# Deployment

`docker compose up --build` runs the local development services. The backend image includes Git and mounts the complete repository at `/workspace` with write access, so `Publisher` can create canonical commits. The host ports bind to `127.0.0.1`; Compose does not publish the Reference Hub or API to the public internet.

Copy `.env.example` to `.env` for local Compose settings. `KNOWLEDGE_REPO_PATH` selects the mounted repository root, and `DATABASE_PATH` selects the Runtime SQLite file. Both default to paths under `/workspace`. The database and `storage/` material remain ignored by Git. DeepSeek configuration is present for a later phase and is not used by the current services.

The production deployment profile, persistent backups, secret handling, and Tailscale / WireGuard access belong to Phase 12. API keys must be supplied to the backend environment and must never be stored in canonical knowledge or committed files.
