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

Before entering private Canonical content, using Publisher, or pushing commits, check the server checkout's Git remote with `git remote -v` and confirm its visibility policy. If Canonical content may be personal or otherwise private, use a private production remote. Tailscale or another VPN protects access to the application server; it does not make a public Git hosting repository private. Never push private Canonical content to a public remote.

Set `DEEPSEEK_API_KEY` through the server's protected environment or secret manager. Keep `.env` out of Git. Check the configured host port and backup directory, then start the services:

Before starting production, run `id -u` and `id -g` as the deployment account and set `KB_RUNTIME_UID` and `KB_RUNTIME_GID` in `.env` to those values. The backend uses that identity when writing the mounted checkout, Runtime database, and storage.

```sh
docker compose -f docker-compose.production.yml config
docker compose -f docker-compose.production.yml up -d --build
docker compose -f docker-compose.production.yml ps
docker compose --env-file .env -f docker-compose.production.yml exec -T backend id
```

Confirm the container's UID and GID match the deployment account before using Publisher. The backend prepares `/tmp/knowledgebase-home` for its Git configuration.

The repository is mounted at `/workspace` so Publisher commits go into the server's Git checkout. `runtime/` and `storage/` persist on that host and are ignored by Git. The Compose file does not publish the API port. Do not change `KB_HTTP_BIND` to `0.0.0.0` on an internet-facing server.

### Existing deployments with root-owned files

This is a one-time migration for an existing deployment whose older root-run backend created root-owned files. Fresh deployments do not need it. Before switching an existing server to the deployment-account backend, make a backup and stop writers: if the Research timer is installed, stop it first, run the production backup entrypoint so an active Research run can finish, then stop the frontend and backend. Inspect ownership as the deployment account:

```sh
cd /srv/KnowledgeBase
id -u
id -g
find .git runtime storage -user root -print
```

Only if the listed files were created by the old KnowledgeBase container and the deployment account should own the whole checkout and its backup/import directories, run once:

```sh
sudo chown -R "$(id -u):$(id -g)" \
  /srv/KnowledgeBase \
  /srv/KnowledgeBase-backups \
  /srv/KnowledgeBase-imports
git status
```

Use the actual paths if the deployment uses custom directories. Confirm `git status` works before starting the updated services. Do not add recursive ownership changes to startup scripts or run them automatically.

### Research Agent scheduler

The Research Agent runs one queued manual request or one due Profile per tick. The first tick is scheduled about two minutes after the timer itself becomes active; later ticks start about two minutes after the previous Research service becomes inactive. The service runtime is added to that idle interval, so this is not a fixed wall-clock two-minute cadence. The monotonic timer does not replay intervals missed while the host is shut down. Install the supplied systemd units on the host; they execute the CLI inside the production backend container and do not require a host Python environment.

Before installing, set `WorkingDirectory` in `deploy/systemd/knowledgebase-research.service` to the server checkout and replace `/usr/bin/docker` with the path returned by `command -v docker` if it differs. Then install and enable the timer:

```sh
sudo cp deploy/systemd/knowledgebase-research.service /etc/systemd/system/
sudo cp deploy/systemd/knowledgebase-research.timer /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now knowledgebase-research.timer
systemctl list-timers knowledgebase-research.timer
```

Validate configuration without contacting providers with `docker compose -f docker-compose.production.yml exec -T backend python /workspace/tools/research.py check`. Use `profiles` to inspect configured Profiles and `status` to review Inbox capacity, pauses, and recent Runs. A scheduled tick exits successfully when another process holds the global Research lock or when nothing is due.

### Safe upgrades

The Research timer runs code from the mounted checkout, while the Web backend runs code from its built image. Pause both during upgrades so a timer tick cannot migrate the shared Runtime database with a different code version. The production checkout may contain Publisher commits that are not on `origin/main`; preserve those commits by merging the fetched target when needed. The worktree must be clean before updating; existing Publisher commits are allowed, but uncommitted changes are not. Never reset the production checkout or rebase Publisher history.

```sh
set -e
cd /srv/KnowledgeBase
sudo systemctl stop knowledgebase-research.timer
systemctl status knowledgebase-research.timer --no-pager || true
./scripts/production-backup.sh
docker compose --env-file .env -f docker-compose.production.yml stop frontend backend
git status
git status --short
test -z "$(git status --porcelain)"
git log --oneline -5
git remote -v
git fetch origin main
TARGET_HEAD="$(git rev-parse origin/main)"
echo "$TARGET_HEAD"
if ! git merge-base --is-ancestor "$TARGET_HEAD" HEAD; then
  git merge --no-edit "$TARGET_HEAD"
fi
test "$(git rev-parse origin/main)" = "$TARGET_HEAD"
git merge-base --is-ancestor "$TARGET_HEAD" HEAD
git status
test -z "$(git status --porcelain)"
git log --oneline --graph -10
docker compose --env-file .env -f docker-compose.production.yml config -q
docker compose --env-file .env -f docker-compose.production.yml build backend frontend
docker compose --env-file .env -f docker-compose.production.yml up -d backend
docker compose --env-file .env -f docker-compose.production.yml ps
docker compose --env-file .env -f docker-compose.production.yml logs --tail=100 backend
docker compose --env-file .env -f docker-compose.production.yml exec -T backend python /workspace/tools/kb.py check
docker compose --env-file .env -f docker-compose.production.yml exec -T backend python /workspace/tools/kb.py rebuild
docker compose --env-file .env -f docker-compose.production.yml exec -T backend python /workspace/tools/research.py check
docker compose --env-file .env -f docker-compose.production.yml up -d frontend
docker compose --env-file .env -f docker-compose.production.yml ps
```

Wait for the backend to become healthy before running the checks. Its startup applies Runtime schema migrations; `kb rebuild` then recreates disposable indexes from Canonical Markdown and YAML. It does not replace or clear `runtime/knowledge.db`. If the merge reports a conflict, stop the upgrade, keep the timer and Web services stopped, retain the backup, and resolve the conflict manually. Do not start production with unresolved conflicts.

Run the production smoke check after the frontend starts:

```sh
for path in \
  api/ui/summary \
  api/library/document-states \
  api/library/source-states \
  api/terms \
  api/terms/candidates \
  api/terms/discovery \
  api/sources \
  api/research/profiles \
  api/proposals \
  api/imports \
  api/review/link-issues \
  api/annotations/stale
do
  curl -fsS "http://127.0.0.1:8080/$path" >/dev/null || exit 1
done
curl -fsS http://127.0.0.1:8080/ >/dev/null
curl -fsS http://127.0.0.1:8080/openapi.json >/dev/null
```

Record a read-only performance baseline without a fixed pass/fail threshold:

```sh
python3 tools/perf_smoke.py --base-url http://127.0.0.1:8080 --repeat 5
```

Only after all checks pass, restart the scheduler and confirm its status:

```sh
sudo systemctl start knowledgebase-research.timer
systemctl status knowledgebase-research.timer --no-pager
```

If any check fails, leave the timer stopped while resolving the issue. The target commit must be an ancestor of production `HEAD`; `HEAD` does not need to equal `TARGET_HEAD` because production may retain Publisher commits.

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

Browser uploads are staged from Library → Import. The server-path form accepts paths beneath `storage/uploads/`. For batch migration, copy a reviewed batch there and use the CLI; for a directory mounted at `/imports` in the production backend, run:

```sh
docker compose -f docker-compose.production.yml exec backend \
  python /workspace/tools/kb.py import /imports --profile legacy
```

Set `KB_IMPORT_DIRECTORY` in the server's `.env` to the host directory to be mounted read-only at `/imports`; the default is `./storage/uploads`. The CLI can also stage arbitrary local paths when run from a checkout with its configured Runtime database.

Review each Markdown item before creating its Draft. Standard imports require valid KnowledgeBase Frontmatter. With the Legacy profile, older Markdown may omit Frontmatter; when its Draft is created, KnowledgeBase synthesizes minimal metadata, marks the note `review.human.status: unreviewed` and `maintenance.status: legacy`, and preserves the original body. Review the generated metadata and refine it before publishing when needed. Open the Draft editor to request a metadata Proposal; the editor requires explicit consent before sending the Draft and registry context to DeepSeek. Review and apply suggested fields manually, then publish through Publisher.

PDF items create Source Drafts only. Review the staged item and confirm the suggested Source ID and title; the PDF is copied to `storage/papers/`. A PDF never creates a Document automatically. Review a representative sample of imported notes and Sources before continuing through the batch.

## Backups

The backup command creates one archive containing:

- a Git bundle with the canonical history and refs;
- a consistent SQLite snapshot, including Drafts, Import Jobs, usage data, and presentation annotations;
- `storage/`, including local PDFs and staged uploads.

The entire Git worktree must be clean before a backup, including Research Profiles under `config/research/profiles/` and `config/research/research.yaml`; the script stops if it finds tracked or untracked changes. Git-ignored Runtime, Storage, and `.env` files do not trigger the check. Runtime and storage data are included in the archive. The default destination is a sibling `KnowledgeBase-backups` directory. Production Compose mounts `KB_BACKUP_DIRECTORY` at `/backups`.

The production backup entrypoint uses the host's `flock` command to wait up to 45 minutes for the shared `runtime/research.lock`. A Research run already holding the lock can finish; new ticks skip while the backup owns it. If the wait times out, the script exits before stopping services. After acquiring the lock, it stops the frontend and backend, runs `backup.py` in a one-off container with the production mounts, then restarts both services even when the backup fails or the script is interrupted. This causes a short service interruption. Run it from the repository root:

```sh
./scripts/production-backup.sh
```

Use the same script for production cron jobs, and copy completed archives to a second private storage location:

```cron
0 2 * * * cd /srv/KnowledgeBase && ./scripts/production-backup.sh >> "$HOME/.local/state/knowledgebase/backup.log" 2>&1
```

Create the log directory for the deployment account before enabling the job. If a timer command lands during the brief service stop, it may fail once and retry on its next scheduled interval. The archive does not contain `.env` or DeepSeek credentials; back those up through the server's secret-management process.

Restore to a new, empty checkout location:

```sh
mkdir -p /tmp/kb-restore
tar -xzf /path/to/knowledgebase-<timestamp>.tar.gz -C /tmp/kb-restore
git clone /tmp/kb-restore/knowledge.bundle /srv/KnowledgeBase
mkdir -p /srv/KnowledgeBase/runtime
cp /tmp/kb-restore/runtime/knowledge.db /srv/KnowledgeBase/runtime/knowledge.db
tar -xzf /tmp/kb-restore/storage.tar.gz -C /srv/KnowledgeBase
```

Cloning the bundle sets `origin` to the temporary bundle path. Before deleting `/tmp/kb-restore` or using Git sync, restore the intended remote from the deployment account:

```sh
cd /srv/KnowledgeBase
git remote -v
```

If production uses a private Git remote, replace the temporary bundle remote and verify it before pushing any Canonical commits:

```sh
git remote remove origin
git remote add origin <your-private-git-remote>
git fetch origin
git remote -v
git status
```

If production does not use a remote, remove the temporary bundle remote instead:

```sh
git remote remove origin
git remote -v
git status
```

Recreate `.env` securely, verify ownership and permissions, then follow the production startup steps. Restoring over a running or populated checkout requires stopping the services and preserving that checkout first.
