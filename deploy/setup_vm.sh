#!/usr/bin/env bash
# Add gridiron-signal to the shared loader VM (sports_db decision 0016, this repo's 0010). Run on the
# VM with sudo after deploy/setup_gcp.sh:
#   sudo bash setup_vm.sh
# Safe to rerun. Pauses once for you to add the VM's deploy key to GitHub. See deploy/README.md.
# It touches only the gridiron user and /etc/logrotate.d/gridiron_signal. Swap, the clock and other
# users stay as they are.
set -euo pipefail

APP_USER="gridiron"
APP_HOME="/home/${APP_USER}"
REPO_DIR="${APP_HOME}/gridiron-signal"
REPO_SSH="git@github.com:khangnguyen518/gridiron-signal.git"
UV_VERSION="0.11.15"

step() { printf '\n== %s\n' "$*"; }
as_app() { sudo -u "$APP_USER" -H bash -lc "$*"; }

step "Packages"
apt-get update -qq
apt-get install -y -qq git cron logrotate curl ca-certificates

step "User $APP_USER"
id "$APP_USER" >/dev/null 2>&1 || useradd --create-home --shell /bin/bash "$APP_USER"

step "uv $UV_VERSION"
as_app "command -v uv >/dev/null && uv --version | grep -q '$UV_VERSION' || curl -LsSf https://astral.sh/uv/$UV_VERSION/install.sh | sh"

step "Deploy key for GitHub (read-only)"
as_app "mkdir -p ~/.ssh && chmod 700 ~/.ssh"
as_app "test -f ~/.ssh/id_ed25519 || ssh-keygen -t ed25519 -N '' -C 'sports-vm gridiron-signal deploy key' -f ~/.ssh/id_ed25519"
as_app "ssh-keyscan -t ed25519 github.com >> ~/.ssh/known_hosts 2>/dev/null; sort -u -o ~/.ssh/known_hosts ~/.ssh/known_hosts"
if [ ! -d "$REPO_DIR/.git" ]; then
  echo
  echo "Add this public key to GitHub as a READ-ONLY deploy key for khangnguyen518/gridiron-signal:"
  echo
  cat "$APP_HOME/.ssh/id_ed25519.pub"
  echo
  read -r -p "Press Enter once the deploy key is added... " _
fi

step "Clone the repo"
as_app "test -d '$REPO_DIR/.git' || git clone '$REPO_SSH' '$REPO_DIR'"
as_app "cd '$REPO_DIR' && git fetch -q origin && git checkout -q main && git pull -q --ff-only"

step "Python dependencies (locked)"
as_app "cd '$REPO_DIR' && uv sync --locked"

step ".env (no secrets: the Discord webhook comes from Secret Manager)"
as_app "test -f '$REPO_DIR/.env' || cat > '$REPO_DIR/.env' <<ENV
NFLM_GCP_PROJECT=gen-lang-client-0525946386
NFLM_DATASET=nflm
NFLM_RAW_DATASET=nflm_raw
NFLM_DBT_TARGET=prod
SPORTS_DB_PROJECT=sports-db-209650
SPORTS_DB_STAGING=staging
FF_PROJECT=gen-lang-client-0525946386
FF_MARTS=ff_marts
SLEEPER_LEAGUE_ID=
SLEEPER_USERNAME=
NFLM_ALERT_SECRET=projects/sports-db-209650/secrets/alert-discord-webhook/versions/latest
ENV
chmod 600 '$REPO_DIR/.env'"
echo "Set SLEEPER_LEAGUE_ID and SLEEPER_USERNAME in $REPO_DIR/.env for the lineup posts."

step "Logs and log rotation"
as_app "mkdir -p '$REPO_DIR/logs'"
cat > /etc/logrotate.d/gridiron_signal <<LOGROTATE
$REPO_DIR/logs/*.log {
    weekly
    rotate 8
    compress
    missingok
    notifempty
    copytruncate
}
LOGROTATE

step "Crontab"
as_app "crontab '$REPO_DIR/deploy/crontab'"
as_app "crontab -l | grep -v '^#' | grep -v '^$'"

step "Done"
echo "Next: run the first refresh by hand (deploy/README.md, step 4)."
