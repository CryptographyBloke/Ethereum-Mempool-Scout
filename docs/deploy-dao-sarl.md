# Deploy to dao.sarl (Railway + Cloudflare)

This application needs **one continuously running container** for both the Ethereum
collector and HTTP API. The SQLite database must survive deployments.

## Railway

1. Create a Railway service from GitHub repository
   `CryptographyBloke/Ethereum-Mempool-Scout` after merging this branch.
   Use the root `Dockerfile` (no frontend-only deployment).
2. Add a **persistent volume** to the service, mounted at `/data`.
   Keep **one replica only**: SQLite is a single-writer database and multiple
   replicas with separate disks will return inconsistent results.
3. Set the following Railway environment variables:
   - `SCOUT_WSS_URL`: your Ethereum mainnet WebSocket RPC endpoint; use a
     provider that supports `eth_subscribe` and `eth_getBlockReceipts`.
     Configure it as a private secret; do not commit API keys.
   - `SCOUT_DB=/data/scout.sqlite`
   - `SCOUT_FETCH_MODE=full` (required for full pending-transaction decoding).
     Use `hash` on limited RPC plans to reduce RPC calls, but some pending
     swap details will be unavailable.
   - `SCOUT_VANTAGE=railway`
   - `SCOUT_CORS_ORIGINS=https://dao.sarl`
   - `PORT=8000` if Railway has not supplied a PORT already.
4. Set the service start command to its Dockerfile default (no override).
   The process manager starts API and collector together, supervises both, and
   terminates them on SIGTERM. Existing `docker compose` collector/serve
   commands continue to work independently.
5. Set the HTTP health-check path to `/api/health`. The endpoint confirms
   database access; check `last_heartbeat_ms` and `head` to verify the
   collector is actually receiving data.
6. Deploy and check the generated `*.up.railway.app` URL first. Check
   `/api/health`, `/api/overview`, and the dashboard. The initial dataset
   will be empty until collection has run long enough.

## Cloudflare (domain bought at Cloudflare)

1. Railway service -> Settings -> Networking -> Custom Domain: add `dao.sarl`.
2. Copy the **exact** CNAME target and any domain-verification TXT record
   supplied by Railway.
3. Cloudflare -> `dao.sarl` -> DNS -> Records: set the root `@` CNAME to
   that Railway target (Cloudflare CNAME flattening supports zone apex). Add
   the TXT verification record when Railway requests one.
4. Start with DNS-only (grey cloud) until domain verification and automatic
   HTTPS certificates complete. Afterwards, enable the Cloudflare proxy only
   if needed and set SSL/TLS mode to **Full (strict)**.
5. Verify `https://dao.sarl/`, `https://dao.sarl/api/health` and live
   `/api/stream` behavior.

**Do not guess the Railway CNAME target.** It is issued when the service
is provisioned. Do not publish your RPC token as a DNS value or repository file.

## Resource and privacy notes

- Continuous mainnet collection consumes outbound RPC quota and persistent
  disk space. Monitor storage growth and Railway usage/billing.
- A single public RPC endpoint measures one vantage point, not Ethereum's
  entire public mempool. Treat dashboards and privacy/MEV comparisons as
  observational measurements with sampling bias.
- The API currently exposes collected records publicly. Deploy a reverse
  proxy access policy if the dataset must remain private.
