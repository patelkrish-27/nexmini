# NexMini

Railway deployment runner for the NexMini Kaggle/ngrok service.

## Repository contents

- `railway/account1-friday.sh` — Account 1 runner
- `railway/account2-saturday.sh` — Account 2 runner
- `railway/README.md` — complete Railway project configuration and debugging guide
- `Dockerfile` — common Python 3.12 runner image

## Railway project

Project: `kaggle-scheduler`

Two services use this same repository:

### Account 1 — Friday night

Service: `kaggle-friday`

- Image: `python:3.12-slim`
- Cron: `30 14 * * 5` (Friday 20:00 IST)
- Start command: `/app/railway/account1-friday.sh`
- Variables: `KAGGLE_API_TOKEN_1`, `KAGGLE_KERNEL_1`

### Account 2 — Saturday daytime

Service: `kaggle-runner`

- Image: `python:3.12-slim`
- Cron: `30 2 * * 6` (Saturday 08:00 IST)
- Start command: `/app/railway/account2-saturday.sh`
- Variables: `KAGGLE_API_TOKEN_2`, `KAGGLE_KERNEL_2`

The tokens and kernel identifiers are intentionally **not** stored in this repository.

## Execution flow

Each Railway job:

1. Installs the Kaggle CLI.
2. Pulls the configured notebook.
3. Pushes it back to Kaggle, which starts the notebook execution.
4. Polls the Kaggle kernel status.
5. Prints final status and Kaggle notebook logs.

The two Kaggle notebooks are expected to expose the same ngrok development domain so the public API address remains unchanged across the account handoff.

## Debugging

A Railway deployment marked `SUCCESS` only confirms the Railway deployment. To confirm the actual remote notebook, inspect the runtime output for:

`[ACCOUNT X STATUS]`, `[ACCOUNT X FINAL STATUS]`, and `[ACCOUNT X KERNEL LOGS]`.

See [railway/README.md](railway/README.md) for local Docker debugging and the exact project configuration.
