#!/bin/sh
# docker-vpn-routes.sh
#
# Adds static routes inside the container so it can reach VPN-connected
# subnets through the host machine (host.docker.internal).
#
# How it works on macOS + Docker Desktop:
#   Container → Docker bridge (172.28.0.1)
#     → Docker Desktop VM
#       → macOS host (reachable via host.docker.internal)
#         → VPN interface (utun*) → 10.40.4.x
#
# Required: cap_add: NET_ADMIN in docker-compose (already set).
# VPN_SUBNETS env var: comma-separated CIDRs, e.g. "10.40.4.0/24,10.40.5.0/24"

set -eu

VPN_SUBNETS="${VPN_SUBNETS:-10.40.4.0/24}"

# Resolve host.docker.internal → the Mac host's IP visible to Docker.
HOST_GW=$(getent hosts host.docker.internal 2>/dev/null | awk '{print $1; exit}')

if [ -z "$HOST_GW" ]; then
    echo "[vpn-routes] WARNING: could not resolve host.docker.internal — skipping VPN route injection"
else
    echo "[vpn-routes] Host gateway: $HOST_GW"
    # Loop over comma-separated CIDRs and add a route for each one.
    echo "$VPN_SUBNETS" | tr ',' '\n' | while read -r CIDR; do
        CIDR=$(echo "$CIDR" | tr -d ' ')
        [ -z "$CIDR" ] && continue
        if ip route add "$CIDR" via "$HOST_GW" 2>/dev/null; then
            echo "[vpn-routes] Added route: $CIDR via $HOST_GW"
        else
            echo "[vpn-routes] Route $CIDR already exists or failed (may be OK)"
        fi
    done
fi

# Hand off to the normal container startup command.
exec /app/backend/app/start.sh
