#!/usr/bin/env bash
# One environment's settings written on the server, without an editor: the
# lines of /etc/caro/<environment>.env that the owner's steps name
# (docs/PHASE1_SETUP.md, step 4, and the phases after it).
#
#   bash /opt/caro/deploy/set-env.sh staging CARO_TURNSTILE_SECRET
#   bash /opt/caro/deploy/set-env.sh production COMPOSE_PROFILES=observe GRAFANA_CLOUD_TOKEN
#
# A name alone is asked for, and what is typed or pasted is not shown: a
# secret is never on the command line, in the shell's history or on the
# screen. NAME=value is written as given, for what is not a secret, and
# NAME= empties it. Piped, one line is read for each name alone:
#
#   openssl rand -hex 32 | bash /opt/caro/deploy/set-env.sh production CARO_WORKER_TOKEN
#
# Every name is checked before anything is written, so a run changes all it
# was asked or nothing:
# - only a name deploy/env.example has is taken, so a mistyped one is said
#   and not silently added;
# - a value an env file does not keep as typed -- a space, #, $, a quote, a
#   backslash -- is refused;
# - the environment's name and path are not changed here, nor a database
#   password that is set: the database was made with it.
# The line is replaced where it is, the rest of the file stays byte for byte,
# mode 600. No value is printed. The environment's timer brings it to the
# file within a minute.
set -euo pipefail

ETC=${CARO_ETC:-/etc/caro}
HERE=$(cd "$(dirname "$0")/.." && pwd)
TEMPLATE=$HERE/deploy/env.example
usage() { echo "usage: bash deploy/set-env.sh production|staging NAME | NAME=value ..." >&2; exit 2; }
die() { echo "set-env: nothing changed: $*" >&2; exit 2; }

ENV=${1:-}
case "$ENV" in
    production|staging) shift ;;
    *) usage ;;
esac
[ "$#" -gt 0 ] || usage
FILE=$ETC/$ENV.env
[ -f "$FILE" ] || die "$FILE is missing: bash $HERE/deploy/bootstrap.sh makes it"

now() { sed -n "s/^$1=//p" "$FILE" | head -n 1; }

NAMES=()
VALUES=()
for arg in "$@"; do
    name=${arg%%=*}
    [[ "$name" =~ ^[A-Z][A-Z0-9_]*$ ]] || die "$name is not a setting's name"
    grep -q "^$name=" "$TEMPLATE" || die "$name is not a setting deploy/env.example has"
    case "$name" in
        CARO_ENV|CARO_ENV_FILE) die "$name is which environment this file is, and is not changed here" ;;
        POSTGRES_PASSWORD)
            [ -z "$(now POSTGRES_PASSWORD)" ] || die "POSTGRES_PASSWORD is set, and the database was made with it" ;;
    esac
    if [ "$arg" != "$name" ]; then
        value=${arg#*=}
    elif [ -t 0 ]; then
        read -rs -p "$name for $ENV (not shown), then Enter: " value
        echo
        [ -n "$value" ] || die "nothing was typed for $name; to empty it: $name="
    else
        IFS= read -r value || [ -n "$value" ] || die "no line to read for $name"
        [ -n "$value" ] || die "an empty line for $name; to empty it: $name="
    fi
    case "$value" in
        *[[:space:]\#\$\'\"\\\`]*) die "the value for $name holds a space, #, \$, a quote or a backslash, which an env file does not keep as typed" ;;
    esac
    NAMES+=("$name")
    VALUES+=("$value")
done

TMP=$(mktemp "$FILE.XXXXXX")
NEXT=
trap 'rm -f "$TMP" $NEXT' EXIT
cat "$FILE" > "$TMP"
for i in "${!NAMES[@]}"; do
    name=${NAMES[$i]} value=${VALUES[$i]} written=0
    NEXT=$(mktemp "$FILE.XXXXXX")
    while IFS= read -r line || [ -n "$line" ]; do
        if [ "${line%%=*}" = "$name" ] && [ "$line" != "$name" ]; then
            # The name's first line is replaced; a second, which would win, goes.
            [ "$written" = 1 ] || printf '%s=%s\n' "$name" "$value"
            written=1
        else
            printf '%s\n' "$line"
        fi
    done < "$TMP" > "$NEXT"
    [ "$written" = 1 ] || printf '%s=%s\n' "$name" "$value" >> "$NEXT"
    mv "$NEXT" "$TMP"
done
chmod 600 "$TMP"
mv "$TMP" "$FILE"
trap - EXIT

for name in "${NAMES[@]}"; do echo "set-env: $ENV: $name written"; done
echo "set-env: the timer brings $ENV to its file within a minute (journalctl -u caro-pull@$ENV)"
