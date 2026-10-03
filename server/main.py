"""NexMini scheduler backend.

Runs the NexMini Kaggle notebook on up to six Kaggle accounts covering
24/7 in 12-hour blocks (see BLOCKS in the code):

  - Account 1: Friday  20:00 -> Saturday 08:00, Sun 08:00-20:00, Thu 20:00-Fri 08:00
  - Account 2: Saturday 08:00 -> Saturday 20:00, Mon 08:00-20:00, Fri 08:00-20:00
  - Account 3: Sat 20:00-Sun 08:00, Tue 08:00-20:00
  - Account 4: Sun 20:00-Mon 08:00, Wed 08:00-20:00
  - Account 5: Mon 20:00-Tue 08:00, Wed 20:00-Thu 08:00
  - Account 6: Tue 20:00-Wed 08:00, Thu 08:00-20:00

Both notebooks expose the same public ngrok URL, so the API endpoint stays
constant across the account handoff.

Environment variables (see .env.example):
  KAGGLE_API_TOKEN_1..6, KAGGLE_KERNEL_1..6
  NGROK_PUBLIC_URL   (e.g. https://renewably-blog-food.ngrok-free.dev)
  KERNEL_TIMEOUT_SECONDS (default 43200 = 12h)
"""

from __future__ import annotations

import json
import logging
import os
import subprocess
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import httpx
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger
from fastapi import BackgroundTasks, FastAPI, HTTPException
from pydantic import BaseModel

IST = ZoneInfo("Asia/Kolkata")
LOG = logging.getLogger("nexmini")
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)

STATE_DIR = Path(os.environ.get("NEXMINI_STATE_DIR", "./state"))
STATE_DIR.mkdir(parents=True, exist_ok=True)
STATE_FILE = STATE_DIR / "state.json"

KERNEL_TIMEOUT = int(os.environ.get("KERNEL_TIMEOUT_SECONDS", "43200"))
NGROK_PUBLIC_URL = os.environ.get("NGROK_PUBLIC_URL", "").rstrip("/")

_lock = threading.Lock()


# ---------------------------------------------------------------- state ----
def _load_state() -> dict[str, Any]:
    if STATE_FILE.exists():
        try:
            return json.loads(STATE_FILE.read_text())
        except Exception:
            pass
    return {"runs": {}, "last_error": None}


def _save_state(state: dict[str, Any]) -> None:
    STATE_FILE.write_text(json.dumps(state, indent=2, default=str))


# --------------------------------------------------------------- kaggle ----
def _kaggle_env(account: int) -> dict[str, str]:
    env = os.environ.copy()
    token = env.get(f"KAGGLE_API_TOKEN_{account}")
    if not token:
        raise RuntimeError(f"KAGGLE_API_TOKEN_{account} is not set")
    env["KAGGLE_API_TOKEN"] = token
    return env


def _kernel(account: int) -> str:
    kernel = os.environ.get(f"KAGGLE_KERNEL_{account}")
    if not kernel:
        raise RuntimeError(f"KAGGLE_KERNEL_{account} is not set")
    return kernel


def _run(cmd: list[str], env: dict[str, str], timeout: int = 900) -> subprocess.CompletedProcess:
    LOG.info("$ %s", " ".join(cmd))
    return subprocess.run(
        cmd, env=env, timeout=timeout,
        capture_output=True, text=True,
    )


def kernel_status(account: int) -> str:
    try:
        p = _run(["kaggle", "kernels", "status", _kernel(account)], _kaggle_env(account), timeout=60)
        out = (p.stdout + p.stderr).strip()
        upper = out.upper()
        for kw in ("RUNNING", "QUEUED", "COMPLETE", "FAILED", "ERROR", "CANCELLED", "STOPPED"):
            if kw in upper:
                return kw
        return out[:120] or "UNKNOWN"
    except Exception as e:
        return f"ERROR: {e}"


def wait_for_kernel_idle(account: int, timeout_s: int = 1800, poll_s: int = 30) -> str:
    """Block until the kernel is no longer RUNNING/QUEUED (used at handoff)."""
    deadline = time.monotonic() + timeout_s
    status = kernel_status(account)
    while status in ("RUNNING", "QUEUED") and time.monotonic() < deadline:
        LOG.info("account %s kernel is %s; waiting before handoff...", account, status)
        time.sleep(poll_s)
        status = kernel_status(account)
    return status


def start_kernel(account: int) -> dict[str, Any]:
    """Pull the notebook from Kaggle and push it, starting a fresh run."""
    kernel = _kernel(account)
    env = _kaggle_env(account)
    workdir = Path(f"/tmp/nexmini-account{account}")
    workdir.mkdir(parents=True, exist_ok=True)

    LOG.info("[A%s] pulling %s", account, kernel)
    pull = _run(["kaggle", "kernels", "pull", kernel, "-p", str(workdir), "-m"], env)
    if pull.returncode != 0:
        raise RuntimeError(f"pull failed: {pull.stderr[-500:]}")

    LOG.info("[A%s] pushing (timeout=%ss)", account, KERNEL_TIMEOUT)
    push = _run(
        ["kaggle", "kernels", "push", "-p", str(workdir), "--timeout", str(KERNEL_TIMEOUT)],
        env, timeout=600,
    )
    if push.returncode != 0:
        raise RuntimeError(f"push failed: {push.stderr[-500:]}")
    LOG.info("[A%s] push ok", account)
    return {"kernel": kernel, "pushed_at": datetime.now(IST).isoformat()}


def run_account(account: int, handoff_from: int | None = None) -> None:
    state = _load_state()
    run_id = datetime.now(IST).isoformat()
    state["runs"][f"account{account}"] = {"started": run_id, "status": "starting"}
    _save_state(state)
    try:
        if handoff_from is not None:
            final = wait_for_kernel_idle(handoff_from)
            LOG.info("[handoff] account %s settled at status %s", handoff_from, final)
        info = start_kernel(account)
        state = _load_state()
        state["runs"][f"account{account}"] = {
            "started": run_id, "status": "pushed", **info,
        }
        state["last_error"] = None
        _save_state(state)
    except Exception as e:
        LOG.exception("account %s run failed", account)
        state = _load_state()
        state["runs"][f"account{account}"] = {"started": run_id, "status": f"failed: {e}"}
        state["last_error"] = str(e)
        _save_state(state)


# ------------------------------------------------------------- scheduler ----
scheduler = BackgroundScheduler(timezone=IST)


# Weekly block table: 12h blocks, Mon..Sun.
# Account 1 (Fri 20:00 -> Sat 08:00) and Account 2 (Sat 08:00 -> Sat 20:00)
# slots are preserved; the rest fills 24/7 coverage with up to 6 accounts.
#
# (start weekday 0=Mon, start hour, account)
BLOCKS: list[tuple[int, int, int]] = [
    (0,  8, 2),  # Mon 08-20
    (0, 20, 5),  # Mon 20-Tue 08
    (1,  8, 3),  # Tue 08-20
    (1, 20, 6),  # Tue 20-Wed 08
    (2,  8, 4),  # Wed 08-20
    (2, 20, 5),  # Wed 20-Thu 08
    (3,  8, 6),  # Thu 08-20
    (3, 20, 1),  # Thu 20-Fri 08
    (4,  8, 2),  # Fri 08-20
    (4, 20, 1),  # Fri 20-Sat 08  (Account 1, unchanged)
    (5,  8, 2),  # Sat 08-20       (Account 2, unchanged)
    (5, 20, 3),  # Sat 20-Sun 08
    (6,  8, 1),  # Sun 08-20
    (6, 20, 4),  # Sun 20-Mon 08
]

_DOW = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]


def account_for(weekday: int, hour: int) -> int:
    """Which account owns the 12h block containing (weekday 0=Mon, hour 0-23)."""
    if hour < 8:      # night block started yesterday 20:00
        weekday, hour = (weekday - 1) % 7, 20
    elif hour >= 20:  # night block starts today 20:00
        hour = 20
    else:             # day block
        hour = 8
    starts = [b for b in BLOCKS if b[0] == weekday and b[1] == hour]
    if not starts:
        raise ValueError(f"no block for {weekday} {hour}")
    return starts[0][2]


def previous_block_account(weekday: int, hour: int) -> int:
    idx = BLOCKS.index(next(b for b in BLOCKS if b[0] == weekday and b[1] == hour))
    return BLOCKS[(idx - 1) % len(BLOCKS)][2]


def current_account(now: datetime | None = None) -> int | None:
    now = now or datetime.now(IST)
    return account_for(now.weekday(), now.hour)


def _make_job(weekday: int, hour: int, account: int):
    def job() -> None:
        LOG.info("cron: starting account %s (block %s %02d:00)", account, _DOW[weekday], hour)
        run_account(account, handoff_from=previous_block_account(weekday, hour))

    return job


def configured(account: int) -> bool:
    return bool(os.environ.get(f"KAGGLE_API_TOKEN_{account}") and os.environ.get(f"KAGGLE_KERNEL_{account}"))


def watchdog() -> None:
    """If the account due right now is not running, start its notebook."""
    if os.environ.get("AUTO_START", "true").lower() not in ("1", "true", "yes"):
        return
    try:
        account = current_account()
        if account is None or not configured(account):
            return
        state = _load_state()
        last = state["runs"].get(f"account{account}", {}).get("started")
        if last:
            age_s = (datetime.now(IST) - datetime.fromisoformat(last)).total_seconds()
            if age_s < 600:  # give a push at least 10 min to reach RUNNING
                return
        status = kernel_status(account)
        if status not in ("RUNNING", "QUEUED"):
            LOG.warning("watchdog: account %s is %s; restarting notebook", account, status)
            now = datetime.now(IST)
            bw, bh = now.weekday(), (8 if 8 <= now.hour < 20 else 20)
            if now.hour < 8:
                bw, bh = (bw - 1) % 7, 20
            run_account(account, handoff_from=previous_block_account(bw, bh))
    except Exception:
        LOG.exception("watchdog error")


def start_scheduler() -> None:
    for weekday, hour, account in BLOCKS:
        token = os.environ.get(f"KAGGLE_API_TOKEN_{account}")
        kernel = os.environ.get(f"KAGGLE_KERNEL_{account}")
        if not token or not kernel:
            LOG.warning(
                "skipping %s %02d:00 block: account %s missing token/kernel env",
                _DOW[weekday], hour, account,
            )
            continue
        scheduler.add_job(
            _make_job(weekday, hour, account),
            CronTrigger(day_of_week=_DOW[weekday], hour=hour, minute=0, timezone=IST),
            id=f"account{account}_{_DOW[weekday]}_{hour:02d}",
            replace_existing=True,
        )
    scheduler.add_job(
        watchdog, IntervalTrigger(minutes=5), id="watchdog", replace_existing=True,
    )
    scheduler.start()
    LOG.info("scheduler started with %d block jobs + watchdog", len(scheduler.get_jobs()))


# ------------------------------------------------------------------ app ----
app = FastAPI(title="NexMini Scheduler", version="1.1.0")


@app.on_event("startup")
def _startup() -> None:
    start_scheduler()
    if os.environ.get("AUTO_START", "true").lower() in ("1", "true", "yes"):
        account = current_account()
        if account is not None:
            status = kernel_status(account)
            LOG.info("startup: inside account %s window, kernel status=%s", account, status)
            if status not in ("RUNNING", "QUEUED"):
                now = datetime.now(IST)
                bw = now.weekday()
                bh = 8 if 8 <= now.hour < 20 else 20
                if now.hour < 8:
                    bw, bh = (bw - 1) % 7, 20
                threading.Thread(
                    target=run_account,
                    args=(account, previous_block_account(bw, bh)),
                    daemon=True,
                ).start()
            else:
                LOG.info("startup: account %s kernel already running, nothing to do", account)
        else:
            LOG.info("startup: outside both windows, no auto-start")


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "time_ist": datetime.now(IST).isoformat()}


@app.get("/schedule")
def schedule() -> dict[str, Any]:
    return {
        "jobs": [
            {"id": j.id, "next_run": str(j.next_run_time)}
            for j in scheduler.get_jobs()
        ]
    }


@app.get("/status")
async def status() -> dict[str, Any]:
    state = _load_state()
    kernels: dict[str, str] = {}
    for i in range(1, 7):
        if os.environ.get(f"KAGGLE_API_TOKEN_{i}") and os.environ.get(f"KAGGLE_KERNEL_{i}"):
            kernels[f"account{i}"] = kernel_status(i)
        else:
            kernels[f"account{i}"] = "not configured"
    tunnel: dict[str, Any] = {"url": NGROK_PUBLIC_URL or None, "reachable": False}
    if NGROK_PUBLIC_URL:
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                r = await client.get(
                    f"{NGROK_PUBLIC_URL}/api/tags",
                    headers={"ngrok-skip-browser-warning": "1"},
                )
                tunnel["reachable"] = r.status_code == 200
                tunnel["http_status"] = r.status_code
        except Exception as e:
            tunnel["error"] = str(e)
    return {
        "time_ist": datetime.now(IST).isoformat(),
        "active_window": current_account(),
        "state": state,
        "kernel_statuses": kernels,
        "tunnel": tunnel,
    }


@app.post("/run/{account}")
def run_now(account: int, background_tasks: BackgroundTasks, handoff: bool = True) -> dict[str, str]:
    if account not in range(1, 7):
        raise HTTPException(400, "account must be 1-6")
    now = datetime.now(IST)
    bw = now.weekday()
    bh = 8 if 8 <= now.hour < 20 else 20
    if now.hour < 8:
        bw, bh = (bw - 1) % 7, 20
    prev = previous_block_account(bw, bh)
    background_tasks.add_task(run_account, account, prev if handoff else None)
    return {"status": f"account {account} run scheduled", "note": "check /status for progress"}


class KernelTestResult(BaseModel):
    kernel: str
    status: str


@app.get("/kernel/{account}/status", response_model=KernelTestResult)
def kernel_status_endpoint(account: int) -> KernelTestResult:
    if account not in range(1, 7):
        raise HTTPException(400, "account must be 1-6")
    return KernelTestResult(kernel=_kernel(account), status=kernel_status(account))
