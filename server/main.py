"""NexMini scheduler backend.

Runs the NexMini Kaggle notebook on two Kaggle accounts on a weekly schedule:

  - Account 1: Friday    20:00 IST  (covers Fri 20:00 -> Sat 08:00)
  - Account 2: Saturday  08:00 IST  (covers Sat 08:00 -> Sat 20:00)

Both notebooks expose the same public ngrok URL, so the API endpoint stays
constant across the account handoff.

Environment variables (see .env.example):
  KAGGLE_API_TOKEN_1, KAGGLE_KERNEL_1
  KAGGLE_API_TOKEN_2, KAGGLE_KERNEL_2
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
        # e.g. "Kernel 'user/kernel' has status 'RUNNING'"
        if "'" in out:
            return out.rsplit("'", 2)[0].rsplit("'", 1)[-1].strip().upper() or out
        return out or "UNKNOWN"
    except Exception as e:
        return f"ERROR: {e}"


def wait_for_kernel_idle(account: int, timeout_s: int = 1800, poll_s: int = 30) -> str:
    """Block until the kernel is no longer RUNNING/QUEUED (used at handoff)."""
    deadline = time.monotonic() + timeout_s
    status = kernel_status(account)
    while status.startswith(("RUNNING", "QUEUED", "KERNEL_STATUS")) and time.monotonic() < deadline:
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


def _job_account1() -> None:
    LOG.info("cron: starting account 1 (Friday night run)")
    run_account(1)


def _job_account2() -> None:
    LOG.info("cron: starting account 2 (Saturday day run)")
    run_account(2, handoff_from=1)


def start_scheduler() -> None:
    scheduler.add_job(
        _job_account1, CronTrigger(day_of_week="fri", hour=20, minute=0, timezone=IST),
        id="account1_friday", replace_existing=True,
    )
    scheduler.add_job(
        _job_account2, CronTrigger(day_of_week="sat", hour=8, minute=0, timezone=IST),
        id="account2_saturday", replace_existing=True,
    )
    scheduler.start()
    LOG.info("scheduler started: A1 Fri 20:00 IST, A2 Sat 08:00 IST")


# ------------------------------------------------------------------ app ----
app = FastAPI(title="NexMini Scheduler", version="1.0.0")


def current_account(now: datetime | None = None) -> int | None:
    """Which account should be live right now, per the weekly schedule."""
    now = now or datetime.now(IST)
    wd, mins = now.weekday(), now.hour * 60 + now.minute  # Mon=0
    if wd == 4 and mins >= 20 * 60:      # Friday >= 20:00
        return 1
    if wd == 5 and mins < 8 * 60:        # Saturday < 08:00 (tail of Friday)
        return 1
    if wd == 5 and mins < 20 * 60:       # Saturday 08:00-20:00
        return 2
    return None                          # Sat >= 20:00 or Sun-Thu


@app.on_event("startup")
def _startup() -> None:
    start_scheduler()
    if os.environ.get("AUTO_START", "true").lower() in ("1", "true", "yes"):
        account = current_account()
        if account is not None:
            status = kernel_status(account)
            LOG.info("startup: inside account %s window, kernel status=%s", account, status)
            if not status.startswith(("RUNNING", "QUEUED")):
                other = 2 if account == 1 else 1
                threading.Thread(
                    target=run_account, args=(account, other), daemon=True,
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
        "kernel_status_1": kernel_status(1) if os.environ.get("KAGGLE_API_TOKEN_1") else "no token",
        "kernel_status_2": kernel_status(2) if os.environ.get("KAGGLE_API_TOKEN_2") else "no token",
        "tunnel": tunnel,
    }


@app.post("/run/{account}")
def run_now(account: int, background_tasks: BackgroundTasks, handoff: bool = True) -> dict[str, str]:
    if account not in (1, 2):
        raise HTTPException(400, "account must be 1 or 2")
    other = 2 if account == 1 else 1
    background_tasks.add_task(run_account, account, other if handoff else None)
    return {"status": f"account {account} run scheduled", "note": "check /status for progress"}


class KernelTestResult(BaseModel):
    kernel: str
    status: str


@app.get("/kernel/{account}/status", response_model=KernelTestResult)
def kernel_status_endpoint(account: int) -> KernelTestResult:
    if account not in (1, 2):
        raise HTTPException(400, "account must be 1 or 2")
    return KernelTestResult(kernel=_kernel(account), status=kernel_status(account))
