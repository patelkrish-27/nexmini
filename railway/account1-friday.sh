#!/bin/sh
set -eu

echo "[ACCOUNT 1 START] $(date -u '+%Y-%m-%d %H:%M:%S UTC')"
pip install --no-cache-dir -q kaggle

: "${KAGGLE_API_TOKEN_1:?KAGGLE_API_TOKEN_1 is required}"
: "${KAGGLE_KERNEL_1:?KAGGLE_KERNEL_1 is required}"

export KAGGLE_API_TOKEN="$KAGGLE_API_TOKEN_1"
export KAGGLE_KERNEL="$KAGGLE_KERNEL_1"

echo "[ACCOUNT 1] Kernel: $KAGGLE_KERNEL"
rm -rf /tmp/kernel && mkdir -p /tmp/kernel

echo "[ACCOUNT 1] Pulling kernel..."
kaggle kernels pull "$KAGGLE_KERNEL" -p /tmp/kernel -m
echo "[ACCOUNT 1] Notebook pulled"

echo "[ACCOUNT 1] Pushing/running kernel..."
kaggle kernels push -p /tmp/kernel --timeout 43200
echo "[ACCOUNT 1] Kaggle push completed"

echo "[ACCOUNT 1] Polling status..."
START_TIME=$(date +%s)
while [ $(( $(date +%s) - START_TIME )) -le 600 ]; do
  STATUS=$(kaggle kernels status "$KAGGLE_KERNEL" 2>&1 || true)
  echo "[ACCOUNT 1 STATUS] $STATUS"
  case "$STATUS" in
    *COMPLETE*|*ERROR*|*FAILED*|*CANCELLED*) break ;;
  esac
  sleep 10
done

echo "[ACCOUNT 1 FINAL STATUS]"
kaggle kernels status "$KAGGLE_KERNEL" 2>&1 || true
echo "[ACCOUNT 1 KERNEL LOGS]"
kaggle kernels logs "$KAGGLE_KERNEL" 2>&1 || true
echo "[ACCOUNT 1 END] $(date -u '+%Y-%m-%d %H:%M:%S UTC')"
