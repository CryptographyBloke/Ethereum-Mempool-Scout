# Running a measurement campaign on a VPS

A measurement only becomes a result when it runs for long enough, without gaps,
from more than one vantage point. This guide sets that up on one small server.

## 1. What to rent

| | Minimum | Recommended |
|---|---|---|
| CPU / RAM | 2 vCPU, 2 GB | 2–4 vCPU, 4 GB |
| Disk | 60 GB SSD | 100 GB SSD |
| OS | Ubuntu 22.04 / 24.04 | same |
| Cost | ~US$5–10 / month | ~US$10–20 / month |

Any mainstream provider works (Hetzner, DigitalOcean, Vultr, AWS Lightsail,
Alibaba Cloud, …). Pick one region and keep it for the whole campaign: write the
region down, because network location affects which transactions reach you first.

**Disk budget.** The 12-minute pilot used about 150 KB per block with a partial
mempool feed, about 1.1 GB per day. A full mempool feed can be 2–3× that. Plan
for **2–3 GB per day**, so a 30-day campaign needs 60–90 GB, plus room for backups.

## 2. Choose your node endpoints

| Role | Needs | Suggestion |
|---|---|---|
| **Primary** (`collector`) | WebSocket, `eth_subscribe`, `eth_getBlockReceipts`, `eth_call`; one `eth_getTransactionByHash` per pending tx | A paid plan on Alchemy / QuickNode / Chainstack, or your own node |
| **Secondary** (`collector-b`) | WebSocket `newPendingTransactions` only (`--fetch-mode hash`) | A different provider from the primary (a free tier usually suffices) |

The primary makes roughly one request per pending transaction it sees (about
1 million or more per day on mainnet). Check this against your plan's quota. If it
does not fit, run the primary with `--fetch-mode hash` too: visibility (RQ1)
still works, but swaps are only decoded from blocks and slippage (RQ2b) is not
measured.

Free endpoints that streamed pending transactions in testing (Nov 2026):
`wss://ethereum-rpc.publicnode.com`, `wss://eth.drpc.org`, `wss://0xrpc.io/eth`.
Their feeds are partial, so use them as extra vantage points, not as the only one.

Running your own node (reth or geth plus a consensus client) gives the most
complete view, but needs about 2 TB of NVMe and 16–32 GB RAM, which is a bigger
machine than this guide assumes.

## 3. Install and start

```bash
# on the VPS
sudo apt-get update && sudo apt-get install -y docker.io docker-compose-v2 git chrony
sudo systemctl enable --now docker chrony
git clone https://github.com/CryptographyBloke/Ethereum-Mempool-Scout.git
cd Ethereum-Mempool-Scout
cp .env.example .env
nano .env                                  # put your endpoints and vantage names in
sudo docker compose --profile multi up -d --build
```

Without a second provider, leave out `--profile multi`.

Check that it is running:

```bash
sudo docker compose ps
sudo docker compose exec api mempool-scout status
sudo docker compose logs -f --tail 20 collector
```

## 4. Look at the dashboard (securely)

The API only listens on `127.0.0.1`. From your laptop, open an SSH tunnel and
browse to http://localhost:8000:

```bash
ssh -L 8000:localhost:8000 user@YOUR_VPS_IP
```

Do not expose port 8000 publicly unless you put authentication in front of it.

## 5. Keep the clock right

All timing (public vs private, inclusion delay, vantage lag) depends on the
server clock. `chrony` (installed above) keeps it synchronised. Check it:

```bash
timedatectl status          # "System clock synchronized: yes"
chronyc tracking            # offset should be well under 10 ms
```

Run all collectors **on the same machine**, so they share one clock.

## 6. Backups

The database lives in the `scout-data` Docker volume. Take a consistent copy
while collectors run, then copy it off the server:

```bash
sudo docker compose exec api mempool-scout backup --out /data/backup-$(date +%F).sqlite
sudo docker compose cp api:/data/backup-$(date +%F).sqlite .
scp user@YOUR_VPS_IP:~/Ethereum-Mempool-Scout/backup-*.sqlite ./   # from your laptop
```

A weekly backup is enough; delete old ones on the server to save disk.

## 7. Monitoring

* `GET /api/health` returns `"ok": true` while at least one collector has a
  heartbeat in the last 60 s, plus per-vantage status. Point any uptime checker
  at it through the tunnel or a reverse proxy.
* `mempool-scout status` prints the same in the terminal.
* Watch disk with `df -h`.

Collectors reconnect automatically and Docker restarts them after crashes or
reboots. Every reconnect is a new *session*, and analysis only counts blocks
inside warmed-up sessions, so short outages lower coverage but never bias results.

## 8. Research protocol

1. **Fix the configuration before you start** (endpoints, vantage names, version)
   and record it in a lab notebook: date, region, providers, git commit.
2. **Run for at least 14 days.** Weekday/weekend and market-volatility effects are
   real, and two weeks gives enough sandwiches for RQ2.
3. **Do not change settings mid-run.** If you must, note the time and treat
   before and after as separate datasets.
4. **Log outages** (provider incidents, server reboots) in the notebook.
5. When the campaign ends:

```bash
sudo docker compose exec api mempool-scout report --out /data/reports
sudo docker compose exec api mempool-scout label-sample --n 100 --out /data/labels.csv
# label the CSV by hand (TP / FP), copy it back to /data, then:
sudo docker compose exec api mempool-scout report --out /data/reports --labels /data/labels.csv
```

The report contains every number for RQ1, RQ1b, RQ2, RQ2b and detector
precision, ready for the write-up.
