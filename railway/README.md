# Railway Kaggle Scheduler

This directory contains the runner code used by the Railway project `kaggle-scheduler`.

## Architecture

The same NexMini Kaggle notebook is maintained under two Kaggle accounts. Railway starts the appropriate account at each handoff:

| Railway service | Kaggle account | Cron (UTC) | India time | Variables |
|---|---|---|---|---|
| `kaggle-friday` | Account 1 | `30 14 * * 5` | Fri 20:00 | `KAGGLE_API_TOKEN_1`, `KAGGLE_KERNEL_1` |
| `kaggle-runner` | Account 2 | `30 2 * * 6` | Sat 08:00 | `KAGGLE_API_TOKEN_2`, `KAGGLE_KERNEL_2` |

Account 1 is intended to cover Friday 20:00–Saturday 08:00 IST.
Account 2 is intended to cover Saturday 08:00–20:00 IST.

Both notebooks are expected to expose the same ngrok development domain.

## Exact Railway configuration

### kaggle-friday

- Image: `python:3.12-slim`
- Restart policy: `NEVER`
- Cron: `30 14 * * 5`
- Start command: `/app/railway/account1-friday.sh`
- Variables:
  - `KAGGLE_API_TOKEN_1`
  - `KAGGLE_KERNEL_1`

### kaggle-runner

- Image: `python:3.12-slim`
- Restart policy: `NEVER`
- Cron: `30 2 * * 6`
- Start command: `/app/railway/account2-saturday.sh`
- Variables:
  - `KAGGLE_API_TOKEN_2`
  - `KAGGLE_KERNEL_2`

## Secrets

No Kaggle tokens, kernel identifiers, usernames, ngrok tokens, or other credentials belong in Git.

Set them only as Railway environment variables.

## Debugging

The scripts deliberately print:

1. container start time
2. Kaggle CLI installation
3. kernel identifier
4. pull result
5. push result
6. repeated Kaggle status
7. final Kaggle status
8. Kaggle notebook logs

This makes authentication, kernel lookup, push, and notebook execution failures visible in Railway logs.

## Important distinction

A Railway deployment marked `SUCCESS` only means Railway successfully deployed the container.

For the actual remote Kaggle notebook, the meaningful evidence is:

```
[ACCOUNT X STATUS]
[ACCOUNT X FINAL STATUS]
[ACCOUNT X KERNEL LOGS]
```

## Local debugging

Build:

```bash
docker build -t nexmini-runner .
```

Run Account 1:

```bash
docker run --rm \
  -e KAGGLE_API_TOKEN_1='YOUR_TOKEN' \
  -e KAGGLE_KERNEL_1='YOUR_USERNAME/YOUR_KERNEL' \
  nexmini-runner /app/railway/account1-friday.sh
```

Run Account 2 similarly with the `_2` variables.

Never commit the real values.
