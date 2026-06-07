#!/usr/bin/env bash
# Run a command with the pipeline's cloud credentials available to the Python
# client libraries.
#
# The cloud-bootstrap SessionStart hook authenticates the gcloud CLI, but the
# google-cloud-* libraries read Application Default Credentials, which the hook
# does not set up. This decrypts the same service-account key to a temp file,
# points ADC (and the sandbox's TLS-proxy CA bundle) at it, runs "$@", and
# shreds the key on exit.
#
#   bash scripts/with-credentials.sh python -m citibike_pipeline.mirror_raw --region jc
set -euo pipefail

KEY="${GCP_CREDENTIALS_KEY:-${CLOUD_CREDENTIALS_KEY:-}}"
ENC=".cloud-credentials.$(git config user.email).enc"
if [ -z "$KEY" ] || [ ! -f "$ENC" ]; then
  echo "with-credentials: need GCP_CREDENTIALS_KEY (or CLOUD_CREDENTIALS_KEY) and $ENC" >&2
  exit 1
fi

TMP="$(mktemp)"
trap 'rm -f "$TMP"' EXIT
umask 077
echo "$KEY" | openssl enc -d -aes-256-cbc -pbkdf2 -pass stdin -in "$ENC" -out "$TMP"

export GOOGLE_APPLICATION_CREDENTIALS="$TMP"
# Sandbox egress proxy does TLS inspection: point every client at the system CA
# bundle (the same one curl/gcloud already trust).
CA=/etc/ssl/certs/ca-certificates.crt
if [ -f "$CA" ]; then
  export REQUESTS_CA_BUNDLE="$CA" SSL_CERT_FILE="$CA" GRPC_DEFAULT_SSL_ROOTS_FILE_PATH="$CA"
fi
export PYTHONPATH="${PYTHONPATH:-src}"

exec "$@"
