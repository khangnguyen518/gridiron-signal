#!/usr/bin/env bash
# One-time GCP setup so the shared loader VM (sports-vm) can refresh gridiron-signal. Run from a
# laptop signed in with gcloud as an owner of the projects below. Safe to rerun. See deploy/README.md
# and decision 0010.
#
# The VM keeps its own service account (the NBA project's default compute account). In this repo's
# project it gets only:
#   - BigQuery job user on the project (dbt and Python run their jobs here)
#   - dataEditor on the prod dataset nflm (created here first)
#   - dataViewer on ff_marts (the draft helper's Sleeper projections, read only)
# sports_db already lets the account read its staging, raw_nfl and raw_meta datasets, and read the
# alert-discord-webhook secret, so nothing changes in sports-db-209650.
set -euo pipefail

PROJECT="${PROJECT:-gen-lang-client-0525946386}"
HOST_PROJECT="${HOST_PROJECT:-nba-analytics-499420}"
SA="${SA:-$(gcloud compute project-info describe --project "$HOST_PROJECT" --format='value(defaultServiceAccount)')}"
DATASET="${DATASET:-nflm}"

step() { printf '\n== %s\n' "$*"; }

# Dataset grants use BigQuery's GRANT statement, like sports_db's setup. Granting twice is harmless.
grant() {
  local role="$1" dataset="$2"
  bq query --quiet --use_legacy_sql=false --location=US --project_id="$PROJECT" \
    "GRANT \`$role\` ON SCHEMA \`$PROJECT\`.$dataset TO \"serviceAccount:$SA\"" >/dev/null
}

step "Host service account: $SA"

step "Project role: BigQuery job user"
gcloud projects add-iam-policy-binding "$PROJECT" --condition=None --quiet \
  --member "serviceAccount:$SA" --role roles/bigquery.jobUser >/dev/null

step "Prod dataset $DATASET"
bq --location=US show "$PROJECT:$DATASET" >/dev/null 2>&1 || bq --location=US mk --dataset "$PROJECT:$DATASET"
grant roles/bigquery.dataEditor "$DATASET"

step "Read only: ff_marts"
grant roles/bigquery.dataViewer ff_marts

step "Done"
echo "Next: run deploy/setup_vm.sh on the VM (deploy/README.md)."
