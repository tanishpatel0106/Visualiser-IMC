# Vercel services deployment

Import the repository with the Vercel project root set to the repository root.
`vercel.json` builds `backend` (FastAPI, `app/main.py`) and `frontend` (Vite)
independently. `/api/*` is routed to the backend without removing `/api`;
all other paths go to the frontend. The backend build copies the four CSV files
already committed in `sample_data/` into its service directory. These repository
files are the initial dataset, not generated or downloaded replacement data.

The static frontend makes requests from the browser to same-origin `/api`.
There are no server-to-server calls and consequently no service bindings.
Do not set a binding URL as `VITE_API_BASE_URL`: service bindings are only
available in runtime functions and cannot be read by a static browser build.
Leave `VITE_API_BASE_URL` and `VITE_WS_BASE_URL` unset for shared-domain routing.

For local service integration, run `vercel dev` from the repository root after
linking the project. Check `/api/health`, `/api/datasets` (loaded sample data),
and `/api/strategies` as well as the frontend page. This requires Vercel account
access and a project that supports services.

## Shared dataset updates

1. Connect a **private Vercel Blob store** to the Vercel project and enable its
   `BLOB_READ_WRITE_TOKEN` environment variable for the backend's deployment.
2. Set a strong, private `IMC_DATA_ADMIN_TOKEN` in Vercel's server environment.
   Do not expose either credential through a `VITE_` variable or commit it.
3. Redeploy to apply the variables. Before any upload, the backend serves the
   repository CSVs. With Blob configured, each dataset request checks for the
   shared replacement using a conditional uncached read.

Upload a **complete replacement dataset** with multipart `files` fields to
`POST /api/datasets/upload`, authenticated with
`Authorization: Bearer <IMC_DATA_ADMIN_TOKEN>`. Filenames must follow
`prices_round_N_day_D.csv` or `trades_round_N_day_D.csv`. For example, using
credentials supplied securely in your local shell:

```bash
curl --fail-with-body "$DEPLOYMENT_URL/api/datasets/upload" \
  -H "Authorization: Bearer $IMC_DATA_ADMIN_TOKEN" \
  -F 'files=@sample_data/prices_round_0_day_-1.csv' \
  -F 'files=@sample_data/prices_round_0_day_-2.csv' \
  -F 'files=@sample_data/trades_round_0_day_-1.csv' \
  -F 'files=@sample_data/trades_round_0_day_-2.csv'
```

The backend validates all files before storing a single private JSON object at
`imc/active-dataset.json`. This gives readers a complete replacement, persists
across restarts and deployments using the same Blob store, and is shared by all
users. Existing process snapshots refresh on their next dataset request. Active
replays must restart after replacement. Concurrent uploads use the last completed
write. There is no upload history or rollback archive.

Uploads accept up to 32 files and 3 MiB of combined UTF-8 CSV contents, below
Vercel's request-body limit. For larger collections, use a future direct-to-Blob
upload flow. The initial repository dataset is bundled at build time and does
not pass through this upload limit.

Admin-authenticated `POST /api/datasets/reset` removes the shared replacement
and restores the bundled repository CSVs for all users. Public read endpoints
remain accessible; uploads and resets fail closed when credentials are absent.
The local-directory `/api/datasets/load` endpoint is disabled on Vercel and when
Blob storage is configured, since it cannot publish a shared durable update.
Temporary local parsing happens in `/tmp`; uploaded data lives durably in Blob.
If Blob becomes unavailable, reads return 503 rather than silently reverting
to an old dataset. Refresh the frontend to retrieve the updated products/days.

For live verification, upload a changed CSV, read it from a fresh backend
instance, and then call reset and confirm the repository products return.
Mocked tests cover these operations without making live Blob writes. A real
Blob store and credentials are required for the live deployment check.

## Runtime limitations

This configuration does not make the full trading terminal production-ready:

- Vercel Functions cannot host the backend's WebSocket server. Live replay at
  `/api/ws/replay` requires a persistent ASGI host or a separate realtime service.
- Replay state and strategy registry changes live in process-local singletons;
  requests across instances or cold starts do not share them.
- On Vercel, SQLite defaults to `/tmp/imc/storage/app.db`, which is writable but
  ephemeral and isolated per instance. Saved runs and uploaded strategies are
  not durable. `IMC_STORAGE_PATH` still overrides the default; use a persistent
  database implementation for production rather than a deployment-directory file.
- Long-running backtests must fit the plan's function duration and resource limits.

For the complete replay and persistence workflow, keep the backend on a persistent
host or plan a separate change for shared state, durable storage, and realtime
transport. The confirmed services are `backend` (public `/api/*`) and `frontend`
(public catch-all), with no service-to-service bindings. Blob is external
storage, not an additional Vercel service in `vercel.json`.
