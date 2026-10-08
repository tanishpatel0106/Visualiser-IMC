# Vercel deployment: NVDA day 0

The confirmed services are `backend` (public `/api/*`) and `frontend` (public
catch-all `/`). Import the repository with the project root at the repository
root. The browser calls same-origin `/api`; there are no runtime service
bindings because there are no server-to-server calls between these services.
Leave `VITE_API_BASE_URL` and `VITE_WS_BASE_URL` unset for shared-domain routing.

## Bundled data and time ranges

`data/nvda/manifest.json` and its gzip chunks contain only NVDA from the real
uploaded day-0 files. All 4,038,507 price snapshots and 318,515 trade prints are
preserved without downsampling, including duplicate-timestamp price updates.
The entire prepared dataset is approximately 15 MB compressed. The original
multi-stock Git LFS pointers are no longer part of the deployment.

The backend build copies `data/nvda` into its service. Startup loads one range,
not the full day. The backend retains at most two ranges in memory, checks
SHA-256 before decompression, and verifies loaded row counts against the
manifest. `/api/datasets` returns NVDA, day 0, totals, and the available ranges.

Use the frontend **RANGE** selector to choose among all 404 time ranges.
Charts, replay, and backtests operate on the selected range, not the full day.
Changing ranges clears the replay state and reloads the chart. API data/replay/
backtest requests use `?window=N`, where N is the range's manifest ID; omitting
it selects range 0. The range boundaries vary because they contain about 10,000
price rows each; records sharing a timestamp stay together. Timestamps retain
the original milliseconds from the start of the trading session.

The bundled data works without Blob credentials. If a private Blob store is
connected but has no active NVDA manifest, the backend also uses the bundle.
Previous uploads stored at `imc/active-dataset.json` do not override this NVDA
bundle; the new active path is `imc/nvda/active-manifest.json`.

## Durable backend replacements

Connect a **private Vercel Blob store** to the Vercel project and configure
`BLOB_READ_WRITE_TOKEN` in the backend's runtime environment. Set a strong
`IMC_DATA_ADMIN_TOKEN` securely in Vercel. Redeploy to apply the variables.
Never commit credentials or expose them through `VITE_` variables.

For small replacements, send multipart `files` to `POST /api/datasets/upload`
with `Authorization: Bearer <IMC_DATA_ADMIN_TOKEN>`. Include
`prices_round_0_day_0.csv` and optionally `trades_round_0_day_0.csv`. The backend
validates the CSVs, extracts only NVDA day 0, prepares bounded gzip ranges,
uploads immutable chunks, then publishes the active manifest after all uploads
succeed. This is a complete replacement, shared across instances and restarts.
Only NVDA is kept if the input contains additional stocks. Requests are limited
to 32 files and 3 MiB combined UTF-8 contents; this is the small-upload option,
not the ingestion path for the original large files.

For large datasets, prepare and publish offline using the included scripts:

```bash
python scripts/prepare_nvda.py --prices /path/to/real/prices.csv \
  --trades /path/to/real/trades.csv --output /path/to/prepared-nvda
# With BLOB_READ_WRITE_TOKEN supplied securely in your shell:
python scripts/publish_nvda.py /path/to/prepared-nvda
```

Preparation requires actual hydrated CSVs and rejects Git LFS pointer files.
Publishing uses the private store's credential and bypasses the function
request-body limit. The active manifest is updated only after every chunk
upload succeeds. Do not publish against a store you do not intend to update.
Chunk paths contain a dataset hash; existing readers keep using their current
version until the new manifest is published. Concurrent publications use the
last completed manifest write. Old chunk versions remain in Blob for safe
reads; there is no automatic storage cleanup or upload history UI.

Admin-authenticated `POST /api/datasets/reset` deletes only the active NVDA
manifest and restores the bundled NVDA data. Existing readers check for updates
on the next dataset request. Refresh the frontend after replacement. Restart
active replays after changing the data. Upload/reset endpoints reject mutations
when credentials are absent. Local-directory `/api/datasets/load` is disabled
for the chunked dataset because it cannot publish a shared durable change.

## Validation and runtime limits

Run `vercel dev` from the repository root with an authenticated linked Vercel
project for services integration. Check `/api/health`, `/api/datasets`, and
`/api/ohlcv?product=NVDA&day=0&window=0`; choose a later range and verify it
returns different timestamps. The backend test suite covers preparation,
range-scoped API requests, checksums, cache bounds, and mocked Blob publication.
Live Blob verification requires usable store credentials.

Dataset display is prepared for Vercel, but these separate limits remain:

- Vercel Functions cannot host the existing `/api/ws/replay` WebSocket server.
- Replay state is process-local and does not survive cold starts or move across
  instances. Shared replay needs a persistent host or shared-state redesign.
- SQLite run/strategy storage defaults to writable but ephemeral `/tmp` on Vercel.
  Blob dataset persistence does not make those results durable.
- Backtests are limited to the selected range and must fit function resource
  and duration limits. Full-day backtesting belongs in an offline workflow or
  a separate worker that streams ranges.
