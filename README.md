# NexMini

Railway deployment runner for the NexMini Kaggle/ngrok service.

## Two ways to run

### Preferred: single backend service (new)

`server/main.py` is a FastAPI service with a built-in scheduler (APScheduler).
Deploy **one** long-running Railway service from this repo — no cron config needed.

- `GET /health` — liveness
- `GET /status` — last runs, Kaggle kernel statuses, ngrok tunnel reachability
- `GET /schedule` — next scheduled runs (Fri 20:00 IST account 1, Sat 08:00 IST account 2)
- `POST /run/1` / `POST /run/2` — manually trigger a notebook run (waits for the other account's kernel to finish first)

```bash
pip install -r server/requirements.txt
cp server/.env.example server/.env   # fill in tokens
uvicorn server.main:app --host 0.0.0.0 --port 8000
```

Railway: set the start command to `uvicorn server.main:app --host 0.0.0.0 --port $PORT`,
set the `KAGGLE_API_TOKEN_1/2`, `KAGGLE_KERNEL_1/2`, `NGROK_PUBLIC_URL` variables,
and **delete/disable the old `kaggle-friday` and `kaggle-runner` cron services**.

See [server/README.md](server/README.md).

### Legacy: cron runner scripts

- `railway/account1-friday.sh` — Account 1 runner
- `railway/account2-saturday.sh` — Account 2 runner
- `railway/README.md` — old Railway cron project configuration and debugging guide
- `Dockerfile` — now builds the backend service (not the cron runners)

## Execution flow

Each run:

1. Installs the Kaggle CLI.
2. Pulls the configured notebook.
3. Pushes it back to Kaggle, which starts the notebook execution (12h timeout).
4. (Account 2 only) waits for the Account 1 kernel to finish before starting,
   so the shared ngrok domain is never claimed by two agents at once.
5. Prints final status and Kaggle notebook logs.

The two Kaggle notebooks are expected to expose the same ngrok development domain so the public API address remains unchanged across the account handoff.

## Debugging

A Railway deployment marked `SUCCESS` only confirms the Railway deployment. Check `/status` for the real Kaggle/ngrok state, and Railway logs for `[ACCOUNT X STATUS]` / `[ACCOUNT X KERNEL LOGS]` lines.
