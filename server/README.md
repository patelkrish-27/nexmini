# NexMini Scheduler Backend

One long-running FastAPI service that starts the NexMini Kaggle notebook
for the right account at each weekly handoff:

| Window (IST) | Account |
|---|---|
| Friday 20:00 → Saturday 08:00 | 1 |
| Saturday 08:00 → Saturday 20:00 | 2 |

Account 2's run waits until Account 1's kernel has finished before pushing,
so the shared ngrok domain is never held by two agents at once.

## Setup

```bash
pip install -r requirements.txt
cp .env.example .env   # fill in real values
```

`.env` values:

```
KAGGLE_API_TOKEN_1=...
KAGGLE_KERNEL_1=username1/nexmini
KAGGLE_API_TOKEN_2=...
KAGGLE_KERNEL_2=username2/nexmini
NGROK_PUBLIC_URL=https://renewably-blog-food.ngrok-free.dev
```

## Run

```bash
uvicorn server.main:app --host 0.0.0.0 --port 8000
```

## Endpoints

- `GET /health` — ok + current IST time
- `GET /schedule` — next cron runs
- `GET /status` — last run state, live Kaggle kernel statuses, ngrok reachability
- `GET /kernel/1/status`, `GET /kernel/2/status`
- `POST /run/1`, `POST /run/2` — manual trigger (waits for other kernel if `handoff=true`)

## Railway

- One service, start command:
  `uvicorn server.main:app --host 0.0.0.0 --port $PORT`
- Set the env variables above in the service settings.
- Restart policy: `ON_FAILURE`.
- Remove the old `kaggle-friday` / `kaggle-runner` cron services so the
  notebook is not pushed twice.

## Notes

- The kernel `--timeout` (default 43200s = 12h) lets Kaggle auto-stop each
  notebook at the end of its window.
- State (last runs, errors) is persisted to `NEXMINI_STATE_DIR/state.json`.
- Free Kaggle accounts gate GPU hours — the handoff wait prevents Account 2
  from queueing while Account 1 is still running.
