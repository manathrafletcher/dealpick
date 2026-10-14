#!/usr/bin/env bash
# Render "Build Command":  bash build.sh
set -euo pipefail
pip install -r requirements.txt

# Litestream copies the SQLite database to a free S3-compatible bucket, so your data survives
# Render's free-tier sleep/restart (the free disk is wiped each time).
LITESTREAM_VERSION="v0.3.13"
curl -fsSL "https://github.com/benbjohnson/litestream/releases/download/${LITESTREAM_VERSION}/litestream-${LITESTREAM_VERSION}-linux-amd64.tar.gz" \
  | tar xz litestream
chmod +x litestream
./litestream version
