#!/bin/sh
set -eu

echo "[KAGGLE NOTEBOOK LIFECYCLE START] $(date -u '+%Y-%m-%d %H:%M:%S UTC')"
echo "Installing kaggle CLI..."
pip install --no-cache-dir -q kaggle

: "${KAGGLE_API_TOKEN_1:?KAGGLE_API_TOKEN_1 is required}"
: "${KAGGLE_KERNEL_1:?KAGGLE_KERNEL_1 is required}"

export KAGGLE_API_TOKEN="$KAGGLE_API_TOKEN_1"
export KAGGLE_KERNEL="$KAGGLE_KERNEL_1"

echo "Kernel identifier: $KAGGLE_KERNEL"
echo "Preparing kernel directory..."
rm -rf /tmp/kernel
mkdir -p /tmp/kernel

echo "Pulling kernel..."
kaggle kernels pull "$KAGGLE_KERNEL" -p /tmp/kernel -m
echo "[NOTEBOOK PULLED] $(date -u '+%Y-%m-%d %H:%M:%S UTC')"

echo "Pushing kernel..."
kaggle kernels push -p /tmp/kernel --timeout 43200
echo "[KAGGLE PUSH COMPLETED] $(date -u '+%Y-%m-%d %H:%M:%S UTC')"

echo "Polling kernel status (10s intervals, 10 min max)..."
START_TIME=$(date +%s)
TIMEOUT_SECS=600
POLL_INTERVAL=10

while true; do
  CURRENT_TIME=$(date +%s)
  ELAPSED=$((CURRENT_TIME - START_TIME))

  if [ "$ELAPSED" -gt "$TIMEOUT_SECS" ]; then
    echo "[STATUS POLL TIMEOUT] Exceeded 10 minutes"
    break
  fi

  STATUS=$(kaggle kernels status "$KAGGLE_KERNEL" 2>&1 || true)
  echo "[STATUS POLL $((ELAPSED / 10 + 1))] $STATUS"

  case "$STATUS" in
    *COMPLETE*|*ERROR*|*FAILED*|*CANCELLED*)
      echo "Terminal state reached: $STATUS"
      break
      ;;
  esac

  sleep "$POLL_INTERVAL"
done

echo "[FINAL STATUS]"
kaggle kernels status "$KAGGLE_KERNEL" 2>&1 || echo "Unable to retrieve"

echo "[KERNEL LOGS]"
kaggle kernels logs "$KAGGLE_KERNEL" 2>&1 || echo "Unable to retrieve logs"

echo "[KAGGLE NOTEBOOK LIFECYCLE END] $(date -u '+%Y-%m-%d %H:%M:%S UTC')"
