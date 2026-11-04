#!/bin/sh
# Writes the two lists of Cloudflare's addresses the edge reads
# (deploy/nginx/caro.conf) into /etc/caro/nginx, from Cloudflare's published
# ranges, and reloads nginx when the edge is running (docs/PHASE1_SETUP.md).
# Run on the server, as root, at setup and daily from its timer. When
# cloudflare.com cannot be read it keeps the lists it has; with none yet, it
# copies the ones in this repository and says so.
set -eu
HERE=$(cd "$(dirname "$0")" && pwd)
OUT=/etc/caro/nginx
mkdir -p "$OUT"
TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT

if curl -fsS --max-time 20 https://www.cloudflare.com/ips-v4 -o "$TMP/v4" \
   && curl -fsS --max-time 20 https://www.cloudflare.com/ips-v6 -o "$TMP/v6"; then
    cat "$TMP/v4" "$TMP/v6" | grep -E '^[0-9a-fA-F:.]+/[0-9]+$' > "$TMP/all" || true
    if [ "$(wc -l < "$TMP/all")" -lt 10 ]; then
        echo "cloudflare-ips: the published lists hold fewer than 10 ranges; keeping the lists in $OUT" >&2
        exit 1
    fi
    { echo "# Cloudflare's ranges, read $(date -u +%Y-%m-%dT%H:%MZ) from cloudflare.com/ips-v4 and /ips-v6."
      sed 's/^/set_real_ip_from /; s/$/;/' "$TMP/all"; } > "$TMP/realip"
    { echo "# Cloudflare's ranges, read $(date -u +%Y-%m-%dT%H:%MZ) from cloudflare.com/ips-v4 and /ips-v6."
      sed 's/$/ 1;/' "$TMP/all"; } > "$TMP/geo"
    install -m 0644 "$TMP/realip" "$OUT/cloudflare-realip.conf"
    install -m 0644 "$TMP/geo" "$OUT/cloudflare-geo.conf"
    echo "cloudflare-ips: $(wc -l < "$TMP/all") ranges written to $OUT"
elif [ ! -s "$OUT/cloudflare-geo.conf" ]; then
    install -m 0644 "$HERE/nginx/cloudflare-realip.conf" "$OUT/cloudflare-realip.conf"
    install -m 0644 "$HERE/nginx/cloudflare-geo.conf" "$OUT/cloudflare-geo.conf"
    echo "cloudflare-ips: cloudflare.com could not be read; the repository's lists copied to $OUT" >&2
else
    echo "cloudflare-ips: cloudflare.com could not be read; keeping the lists in $OUT" >&2
fi

EDGE=$(docker ps -q --filter label=com.docker.compose.project=caro-edge \
                   --filter label=com.docker.compose.service=nginx 2>/dev/null || true)
if [ -n "$EDGE" ]; then
    docker exec "$EDGE" nginx -t -q && docker exec "$EDGE" nginx -s reload
fi
