#!/bin/sh
set -eu

echo "[ACCOUNT 2 START] $(date -u '+%Y-%m-%d %H:%M:%S UTC')"
pip install --no-cache-dir -q kaggle

: "${KAGGLE_API_TOKEN_2:?KAGGLE_API_TOKEN_2 is required}"
: "${KAGGLE_KERNEL_2:?KAGGLE_KERNEL_2 is required}"

export KAGGLE_API_TOKEN="$KAGGLE_API_TOKEN_2"
export KAGGLE_KERNEL="$KAGGLE_KERNEL_2"

echo "[ACCOUNT 2] Kernel: $KAGGLE_KERNEL"
rm -rf /tmp/kernel && mkdir -p /tmp/kernel

echo "[ACCOUNT 2] Pulling kernel..."
kaggle kernels pull "$KAGGLE_KERNEL" -p /tmp/kernel -m
echo "[ACCOUNT 2] Notebook pulled"

echo "[ACCOUNT 2] Pushing/running kernel..."
kaggle kernels push -p /tmp/kernel --timeout 43200
echo "[ACCOUNT 2] Kaggle push completed"

echo "[ACCOUNT 2] Polling status..."
START_TIME=$(date +%s)
while [ $(( $(date +%s) - START_TIME )) -le 600 ]; do
  STATUS=$(kaggle kernels status "$KAGGLE_KERNEL" 2>&1 || true)
  echo "[ACCOUNT 2 STATUS] $STATUS"
  case "$STATUS" in
    *COMPLETE*|*ERROR*|*FAILED*|*CANCELLED*) break ;;
  esac
  sleep 10
done

echo "[ACCOUNT 2 FINAL STATUS]"
kaggle kernels status "$KAGGLE_KERNEL" 2>&1 || true
echo "[ACCOUNT 2 KERNEL LOGS]"
kaggle kernels logs "$KAGGLE_KERNEL" 2>&1 || true
echo "[ACCOUNT 2 END] $(date -u '+%Y-%m-%d %H:%M:%S UTC')"
