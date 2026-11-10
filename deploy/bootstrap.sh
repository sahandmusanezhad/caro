#!/usr/bin/env bash
# The server's side of phase 1 (docs/PHASE1_SETUP.md, steps 2, 3, 4, 6 and 7),
# on the server, as root:
#
#   bash /opt/caro/deploy/bootstrap.sh                the server and staging
#   bash /opt/caro/deploy/bootstrap.sh --production   and production, after
#                                                     the first release tag
#
# Each part is done only where it is not done yet, so it can be run again at
# any time; it ends by saying what is left, which is what only the owner
# holds. In order:
# 1. Docker, from get.docker.com, after the system's upgrades.
# 2. /etc/caro and its tls directory, mode 700, its nginx directory, and
#    Cloudflare's ranges in the last (deploy/cloudflare-ips.sh).
# 3. Each environment's settings, from deploy/env.example: its name, its own
#    path, its images' tag, its origin and host, and a database password of
#    its own, made here and printed nowhere. A file that is there is never
#    written again.
# 4. The units (deploy/systemd).
# 5. The origin certificate, when CLOUDFLARE_API_TOKEN is set: the key is
#    made here and stays here (scripts/cloudflare_setup.py origin-cert).
# 6. With the certificate in place, the edge, then the timers: the ranges'
#    and staging's pull, and production's with --production. Before it, an
#    environment's pull would only fail on the edge's network.
set -euo pipefail

CARO_HOME=${CARO_HOME:-/opt/caro}
ETC=${CARO_ETC:-/etc/caro}
UNITS=${CARO_UNITS:-/etc/systemd/system}
IMAGES=ghcr.io/sahandmusanezhad
HERE=$(cd "$(dirname "$0")/.." && pwd)
PRODUCTION=0
case "${1:-}" in
    --production) PRODUCTION=1 ;;
    "") ;;
    *) echo "usage: bash deploy/bootstrap.sh [--production]" >&2; exit 2 ;;
esac

LEFT=()
say() { echo "bootstrap: $*"; }
left() { LEFT+=("$*"); }
die() { echo "bootstrap: stopped: $*" >&2; exit 2; }

[ "$HERE" = "$CARO_HOME" ] || die "this checkout is $HERE, and the units run $CARO_HOME: git clone https://github.com/sahandmusanezhad/caro $CARO_HOME"
[ -w "$(dirname "$ETC")" ] || die "$(dirname "$ETC") cannot be written here: run it as root"

# ---- 1. Docker ---------------------------------------------------------------
if command -v docker >/dev/null 2>&1; then
    say "Docker: there already"
else
    say "Docker: installing, after the system's upgrades"
    apt-get update -q
    DEBIAN_FRONTEND=noninteractive apt-get -y -q \
        -o Dpkg::Options::=--force-confdef -o Dpkg::Options::=--force-confold upgrade
    curl -fsSL https://get.docker.com | sh
    command -v docker >/dev/null 2>&1 || die "Docker did not install"
fi
docker compose version >/dev/null 2>&1 || die "Docker is there without compose: apt-get install -y docker-compose-plugin"

# ---- 2. The directories, and Cloudflare's ranges -----------------------------
install -d -m 0700 "$ETC" "$ETC/tls"
install -d -m 0755 "$ETC/nginx"
CARO_ETC=$ETC sh "$HERE/deploy/cloudflare-ips.sh" || say "Cloudflare's ranges: not refreshed"
{ [ -s "$ETC/nginx/cloudflare-geo.conf" ] && [ -s "$ETC/nginx/cloudflare-realip.conf" ]; } \
    || die "no list of Cloudflare's ranges in $ETC/nginx, and the edge does not start without: run this again"

# ---- 3. Each environment's settings ------------------------------------------
make_env() {  # environment, the host it is served at
    local env=$1 host=$2 f="$ETC/$1.env" pw
    if [ -e "$f" ]; then
        say "$f: there already, not written"
        return
    fi
    pw=$(openssl rand -hex 24)
    (umask 077 && sed -e "s|^CARO_ENV=.*|CARO_ENV=$env|" \
                      -e "s|^CARO_ENV_FILE=.*|CARO_ENV_FILE=$f|" \
                      -e "s|^CARO_API_IMAGE=.*|CARO_API_IMAGE=$IMAGES/caro-api:$env|" \
                      -e "s|^CARO_SITE_IMAGE=.*|CARO_SITE_IMAGE=$IMAGES/caro-site:$env|" \
                      -e "s|^POSTGRES_PASSWORD=.*|POSTGRES_PASSWORD=$pw|" \
                      -e "s|^CARO_SITE_ORIGINS=.*|CARO_SITE_ORIGINS=https://$host|" \
                      -e "s|^CARO_SITE_HOST=.*|CARO_SITE_HOST=$host|" \
                      "$HERE/deploy/env.example" > "$f.new")
    chmod 600 "$f.new"
    mv "$f.new" "$f"
    say "$f: made, for $host, with a database password of its own"
}
make_env production caro.noxioai.com
make_env staging caro-staging.noxioai.com
for env in staging production; do
    empty=$(grep -oE '^(CARO_ADMIN_TOKEN|CARO_ADMIN_TOTP_SECRET)=$' "$ETC/$env.env" | tr -d '=' | tr '\n' ' ' || true)
    [ -z "$empty" ] || left "$ETC/$env.env: ${empty}as on Vercel today (nano $ETC/$env.env; PHASE1_SETUP, step 4)"
done

# ---- 4. The units --------------------------------------------------------------
install -m 0644 "$HERE"/deploy/systemd/caro-* "$UNITS/"
systemctl daemon-reload
say "the units: in $UNITS"

# ---- 5. The origin certificate -------------------------------------------------
cert() { [ -s "$ETC/tls/origin.pem" ] && [ -s "$ETC/tls/origin.key" ]; }
if ! cert && [ -n "${CLOUDFLARE_API_TOKEN:-}" ]; then
    python3 "$HERE/scripts/cloudflare_setup.py" origin-cert --tls-dir "$ETC/tls" \
        || say "the origin certificate: not made; the line above says why"
fi

# ---- 6. The edge, then the timers ------------------------------------------------
# An image the server cannot read is a package still private (step 5), or a
# tag not pushed yet (step 7): said here, since its pull would only fail.
readable() { docker manifest inspect "$IMAGES/caro-api:$1" >/dev/null 2>&1; }
if cert; then
    docker compose -p caro-edge -f "$HERE/compose.edge.yml" up -d --quiet-pull
    say "the edge: up"
    systemctl enable --now caro-cloudflare-ips.timer caro-pull@staging.timer
    say "staging: brought to its image every minute (journalctl -u caro-pull@staging)"
    readable staging || left "the images, readable by the server (PHASE1_SETUP, step 5): on GitHub, your profile -> Packages -> caro-api, then caro-site -> Package settings -> Change visibility -> Public"
    if [ "$PRODUCTION" != 1 ]; then
        left "production, after the release tag v1.0.0 (PHASE1_SETUP, step 7): bash $HERE/deploy/bootstrap.sh --production"
    elif readable production; then
        systemctl enable --now caro-pull@production.timer
        say "production: brought to its image every minute (journalctl -u caro-pull@production)"
    else
        left "production's images are not there to read: the release tag first (PHASE1_SETUP, step 7), then this again with --production"
    fi
else
    left "the origin certificate: read -rs CLOUDFLARE_API_TOKEN && export CLOUDFLARE_API_TOKEN, then this again (scripts/cloudflare_setup.py names the token's permissions)"
fi

# Staging's name: done when staging answers through it (PHASE1_SETUP, step 6).
# The server's own address is the first that is not inside a network: Docker's
# bridges and a private network have addresses too.
addr=$(ip -4 -o addr show scope global 2>/dev/null | awk '{print $4}' | cut -d/ -f1 \
       | grep -vE '^(10\.|192\.168\.|172\.(1[6-9]|2[0-9]|3[01])\.|100\.(6[4-9]|[7-9][0-9]|1[01][0-9]|12[0-7])\.)' \
       | head -n 1 || true)
if cert && curl -fsS -m 10 -o /dev/null https://caro-staging.noxioai.com/api/health 2>/dev/null; then
    say "staging: answers at https://caro-staging.noxioai.com"
elif [ -n "$addr" ]; then
    left "staging's name, from any machine with the token: python3 scripts/cloudflare_setup.py staging --ip $addr"
fi

if [ "${#LEFT[@]}" = 0 ]; then
    say "nothing is left here"
else
    say "left, for the owner:"
    for l in "${LEFT[@]}"; do echo "  - $l"; done
fi
