# Deployment

For the step-by-step Chinese operator guide, see [服务启用与运维手册](服务启用与运维手册.md).

## Local development

`docker compose up --build` runs the Vite development server and backend. Both ports bind to `127.0.0.1`; neither service is published publicly. Copy `.env.example` to `.env` for local settings.

## Private production deployment

The production Compose file builds a static Reference Hub served by Nginx and a FastAPI backend. The backend port is available only on the Compose network. The Hub binds to `127.0.0.1:8080` by default, and Nginx proxies `/api`, `/docs`, and `/openapi.json` to the backend.

On a new private server:

```sh
git clone <your-private-git-remote> /srv/KnowledgeBase
cd /srv/KnowledgeBase
cp .env.example .env
```

Set `DEEPSEEK_API_KEY` through the server's protected environment or secret manager. Keep `.env` out of Git. Check the configured host port and backup directory, then start the services:

```sh
docker compose -f docker-compose.production.yml config
docker compose -f docker-compose.production.yml up -d --build
docker compose -f docker-compose.production.yml ps
```

The repository is mounted at `/workspace` so Publisher commits go into the server's Git checkout. `runtime/` and `storage/` persist on that host and are ignored by Git. The Compose file does not publish the API port. Do not change `KB_HTTP_BIND` to `0.0.0.0` on an internet-facing server.

### Tailscale

Install and sign in to Tailscale on the server host, then serve the loopback-only Hub to the tailnet:

```sh
sudo tailscale serve --bg http://127.0.0.1:8080
sudo tailscale serve status
```

Tailscale Serve provides HTTPS within the tailnet; HTTPS certificates must be enabled for the tailnet, and its access-control rules apply. Do not use Funnel for this private KnowledgeBase. See the [Tailscale Serve guide](https://tailscale.com/docs/features/tailscale-serve) and [CLI reference](https://tailscale.com/docs/reference/tailscale-cli/serve) for current setup requirements.

### WireGuard

For a WireGuard host, set `KB_HTTP_BIND` to the server's WireGuard interface address and allow `KB_HTTP_PORT` only from the VPN interface in the host firewall. Keep the API port unpublished. TLS can terminate at a reverse proxy reachable only through that interface.

## Legacy migration

The Reference Hub Import Review accepts paths beneath `storage/uploads/`. Copy a reviewed batch there, select the Legacy profile, and stage the directory. For a directory mounted at `/imports` in the production backend, use:

```sh
docker compose -f docker-compose.production.yml exec backend \
  python /workspace/tools/kb.py import /imports --profile legacy
```

Set `KB_IMPORT_DIRECTORY` in the server's `.env` to the host directory to be mounted read-only at `/imports`; the default is `./storage/uploads`. The CLI can also stage arbitrary local paths when run from a checkout with its configured Runtime database.

Review each Markdown item before creating its Draft. Standard imports require valid KnowledgeBase Frontmatter. With the Legacy profile, older Markdown may omit Frontmatter; when its Draft is created, KnowledgeBase synthesizes minimal metadata, marks the note `review.human.status: unreviewed` and `maintenance.status: legacy`, and preserves the original body. Review the generated metadata and refine it before publishing when needed. Open the Draft editor to request a metadata Proposal; the editor requires explicit consent before sending the Draft and registry context to DeepSeek. Review and apply suggested fields manually, then publish through Publisher.

PDF items create Source Drafts only. Confirm the suggested Source ID and title in Import Review; the PDF is copied to `storage/papers/`. A PDF never creates a Document automatically. Review a representative sample of imported notes and Sources before continuing through the batch.

## Backups

The backup command creates one archive containing:

- a Git bundle with the canonical history and refs;
- a consistent SQLite snapshot, including Drafts, Import Jobs, usage data, and presentation annotations;
- `storage/`, including local PDFs and staged uploads.

Canonical changes under `knowledge/` must be committed before a backup; the script stops if they are dirty. Runtime and storage data are included even though Git ignores them. The default destination is a sibling `KnowledgeBase-backups` directory. Production Compose mounts `KB_BACKUP_DIRECTORY` at `/backups`.

Create an archive:

```sh
docker compose -f docker-compose.production.yml exec -T backend \
  python /workspace/scripts/backup.py
```

Schedule that command on the server and copy completed archives to a second private storage location. The archive does not contain `.env` or DeepSeek credentials; back those up through the server's secret-management process.

Restore to a new, empty checkout location:

```sh
mkdir -p /tmp/kb-restore
tar -xzf /path/to/knowledgebase-<timestamp>.tar.gz -C /tmp/kb-restore
git clone /tmp/kb-restore/knowledge.bundle /srv/KnowledgeBase
mkdir -p /srv/KnowledgeBase/runtime
cp /tmp/kb-restore/runtime/knowledge.db /srv/KnowledgeBase/runtime/knowledge.db
tar -xzf /tmp/kb-restore/storage.tar.gz -C /srv/KnowledgeBase
```

Recreate `.env` securely, verify ownership and permissions, then follow the production startup steps. Restoring over a running or populated checkout requires stopping the services and preserving that checkout first.
