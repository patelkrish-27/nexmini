# NexMini Scheduler Backend

One long-running FastAPI service that starts the NexMini Kaggle notebook
on up to six Kaggle accounts, covering 24/7 in 12-hour blocks at the same
public ngrok URL:

| Starts (IST) | Account | Next (IST) | Account |
|---|---|---|---|
| Mon 08:00 | 2 | Mon 20:00 | 5 |
| Tue 08:00 | 3 | Tue 20:00 | 6 |
| Wed 08:00 | 4 | Wed 20:00 | 5 |
| Thu 08:00 | 6 | Thu 20:00 | 1 |
| Fri 08:00 | 2 | Fri 20:00 | 1 |
| Sat 08:00 | 2 | Sat 20:00 | 3 |
| Sun 08:00 | 1 | Sun 20:00 | 4 |

Account 1 (Fri 8pm → Sat 8am) and Account 2 (Sat 8am → 8pm) slots are
unchanged. Every start waits for the previous block's kernel to finish,
so the shared ngrok domain is never held by two agents at once.

Hours per account per week: A1 36h, A2 36h, A3/A4/A5/A6 24h each.

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
- `GET /status` — last run state, live Kaggle kernel statuses (all 6), ngrok reachability
- `GET /kernel/{1..6}/status`
- `POST /run/{1..6}` — manual trigger (waits for the previous block's kernel if `handoff=true`)

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
