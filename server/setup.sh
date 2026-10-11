#!/usr/bin/env bash
# STEELWARS -- installs the dedicated server on a Linux machine with systemd.
#
#   sudo ./setup.sh [--port 27960] [--turn-ms 100] [--max-clients 64] [--no-firewall]
#   sudo ./setup.sh --uninstall
#
# Run it from the unpacked package (build.sh makes it). It
#   - takes the bundled binary, or builds one from src/ where that does not run
#     (another CPU), installing a compiler first if there is none;
#   - installs it to /opt/steelwars-server, the settings to
#     /etc/steelwars-server.conf;
#   - sets up the systemd service steelwars-server (its own throwaway user,
#     no write access anywhere, restarted when it fails, started at boot);
#   - opens the TCP port in ufw or firewalld, when one of them is active;
#   - checks the server answers.
# Run it again to update (the settings stay unless given anew), or to change
# them. Players enter the server's address and port under Netzwerkspiel.
set -euo pipefail

NAME="steelwars-server"
INSTALL_DIR="/opt/$NAME"
CONF="/etc/$NAME.conf"
UNIT="/etc/systemd/system/$NAME.service"
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

PORT="" TURN_MS="" MAX_CLIENTS="" FIREWALL=1 UNINSTALL=0
ARGS=("$@")

say()  { printf '\033[1;33m==\033[0m %s\n' "$*"; }
warn() { printf '\033[1;31m!!\033[0m %s\n' "$*" >&2; }
die()  { warn "$*"; exit 1; }

# The comment at the top of this file.
usage() {
    awk 'NR > 1 && /^#/ { sub(/^# ?/, ""); print; next } NR > 1 { exit }' "${BASH_SOURCE[0]}"
    exit "${1:-0}"
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --port)        PORT="${2:-}"; shift 2 ;;
        --turn-ms)     TURN_MS="${2:-}"; shift 2 ;;
        --max-clients) MAX_CLIENTS="${2:-}"; shift 2 ;;
        --no-firewall) FIREWALL=0; shift ;;
        --uninstall)   UNINSTALL=1; shift ;;
        -h|--help)     usage 0 ;;
        *)             warn "unknown option: $1"; usage 2 ;;
    esac
done

isNumber() { [[ "$1" =~ ^[0-9]+$ ]]; }
for opt in port:PORT turn-ms:TURN_MS max-clients:MAX_CLIENTS; do
    var="${opt#*:}"
    val="${!var}"
    [[ -z "$val" ]] || isNumber "$val" || die "--${opt%%:*}: not a number: $val"
done
[[ -z "$PORT" ]] || (( PORT >= 1 && PORT <= 65535 )) || die "--port: 1..65535"

[[ $EUID -eq 0 ]] || die "run as root: sudo $0 ${ARGS[*]}"
[[ -d /run/systemd/system ]] || die "this machine does not run systemd -- start $INSTALL_DIR/fitzelserver by hand instead"

# --- The firewall --------------------------------------------------------------
firewallOpen() {
    local port="$1"
    if command -v ufw >/dev/null && ufw status 2>/dev/null | grep -q "^Status: active"; then
        ufw allow "$port/tcp" comment "Steelwars server" >/dev/null && say "ufw: port $port/tcp open"
    elif command -v firewall-cmd >/dev/null && firewall-cmd --state >/dev/null 2>&1; then
        firewall-cmd --quiet --permanent --add-port="$port/tcp" && firewall-cmd --quiet --reload \
            && say "firewalld: port $port/tcp open"
    else
        say "no active ufw/firewalld here -- nothing to open locally"
    fi
}
firewallClose() {
    local port="$1"
    if command -v ufw >/dev/null && ufw status 2>/dev/null | grep -q "^Status: active"; then
        ufw delete allow "$port/tcp" >/dev/null 2>&1 && say "ufw: port $port/tcp closed" || true
    elif command -v firewall-cmd >/dev/null && firewall-cmd --state >/dev/null 2>&1; then
        firewall-cmd --quiet --permanent --remove-port="$port/tcp" 2>/dev/null && firewall-cmd --quiet --reload \
            && say "firewalld: port $port/tcp closed" || true
    fi
}

# What is installed now (empty when nothing is).
OLD_PORT="" OLD_TURN_MS="" OLD_MAX_CLIENTS=""
if [[ -f "$CONF" ]]; then
    OLD_PORT="$(sed -n 's/^PORT=\([0-9]*\).*/\1/p' "$CONF")"
    OLD_TURN_MS="$(sed -n 's/^TURN_MS=\([0-9]*\).*/\1/p' "$CONF")"
    OLD_MAX_CLIENTS="$(sed -n 's/^MAX_CLIENTS=\([0-9]*\).*/\1/p' "$CONF")"
fi

# --- Uninstall -------------------------------------------------------------------
if [[ $UNINSTALL -eq 1 ]]; then
    say "removing $NAME"
    systemctl disable --now "$NAME" 2>/dev/null || true
    rm -f "$UNIT"
    systemctl daemon-reload
    [[ -n "$OLD_PORT" && $FIREWALL -eq 1 ]] && firewallClose "$OLD_PORT"
    rm -rf "$INSTALL_DIR"
    rm -f "$CONF"
    say "done"
    exit 0
fi

PORT="${PORT:-${OLD_PORT:-27960}}"
TURN_MS="${TURN_MS:-${OLD_TURN_MS:-100}}"
MAX_CLIENTS="${MAX_CLIENTS:-${OLD_MAX_CLIENTS:-64}}"

# --- The binary ------------------------------------------------------------------
installCompiler() {
    say "no C++ compiler -- installing one"
    if   command -v apt-get >/dev/null; then apt-get update -qq && DEBIAN_FRONTEND=noninteractive apt-get install -y -qq g++
    elif command -v dnf     >/dev/null; then dnf install -y -q gcc-c++
    elif command -v yum     >/dev/null; then yum install -y -q gcc-c++
    elif command -v zypper  >/dev/null; then zypper --non-interactive install gcc-c++
    elif command -v pacman  >/dev/null; then pacman -S --noconfirm --needed gcc
    elif command -v apk     >/dev/null; then apk add --no-cache g++
    else die "no package manager I know -- install a C++ compiler (g++) and run this again"
    fi
}

BIN="$HERE/bin/fitzelserver"
if [[ -x "$BIN" ]] && "$BIN" --help >/dev/null 2>&1; then
    say "using the bundled binary ($(uname -m))"
else
    [[ -f "$HERE/src/fitzelserver.cpp" ]] || die "no binary that runs here and no src/ to build one -- is this the unpacked package?"
    say "the bundled binary does not run on $(uname -m) -- building from src/"
    CXX="$(command -v g++ || command -v c++ || command -v clang++ || true)"
    if [[ -z "$CXX" ]]; then
        installCompiler
        CXX="$(command -v g++ || command -v c++)"
    fi
    BIN="$(mktemp -d)/fitzelserver"
    "$CXX" -std=c++17 -O2 -s -I"$HERE/src" "$HERE/src/fitzelserver.cpp" "$HERE/src/NetRelay.cpp" \
        "$HERE/src/NetSocket.cpp" -o "$BIN" || die "build failed"
    "$BIN" --help >/dev/null || die "the binary just built does not run"
fi

WAS_RUNNING=0
systemctl is-active --quiet "$NAME" 2>/dev/null && WAS_RUNNING=1

say "installing to $INSTALL_DIR"
install -d -m 755 "$INSTALL_DIR"
install -m 755 "$BIN" "$INSTALL_DIR/fitzelserver.new"
mv -f "$INSTALL_DIR/fitzelserver.new" "$INSTALL_DIR/fitzelserver"
[[ -f "$HERE/VERSION" ]] && install -m 644 "$HERE/VERSION" "$INSTALL_DIR/VERSION"

cat > "$CONF" <<EOF
# Steelwars server -- sudo systemctl restart $NAME after a change
# (or run setup.sh again with --port/--turn-ms/--max-clients).

# TCP port the players connect to
PORT=$PORT
# lockstep turn length (ms); the clients take it from the server
TURN_MS=$TURN_MS
# connections at once, players in lobbies and in games
MAX_CLIENTS=$MAX_CLIENTS
EOF
chmod 644 "$CONF"

cat > "$UNIT" <<EOF
[Unit]
Description=Steelwars multiplayer server (Fitzel lockstep relay)
Documentation=file://$INSTALL_DIR/VERSION
After=network-online.target
Wants=network-online.target

[Service]
EnvironmentFile=$CONF
ExecStart=$INSTALL_DIR/fitzelserver --port \${PORT} --turn-ms \${TURN_MS} --max-clients \${MAX_CLIENTS}
Restart=on-failure
RestartSec=3

# Its own throwaway user, and nothing it may write or reach beyond its sockets.
DynamicUser=yes
NoNewPrivileges=yes
ProtectSystem=strict
ProtectHome=yes
PrivateTmp=yes
PrivateDevices=yes
ProtectKernelTunables=yes
ProtectKernelModules=yes
ProtectKernelLogs=yes
ProtectControlGroups=yes
ProtectClock=yes
ProtectHostname=yes
RestrictAddressFamilies=AF_INET AF_INET6
RestrictNamespaces=yes
RestrictRealtime=yes
RestrictSUIDSGID=yes
LockPersonality=yes
MemoryDenyWriteExecute=yes
SystemCallArchitectures=native
SystemCallFilter=@system-service
SystemCallFilter=~@privileged @resources
ProtectProc=invisible
ProcSubset=pid
RemoveIPC=yes
UMask=0077
# a port below 1024 needs this one capability, nothing else
CapabilityBoundingSet=CAP_NET_BIND_SERVICE
AmbientCapabilities=CAP_NET_BIND_SERVICE
LimitNOFILE=4096

[Install]
WantedBy=multi-user.target
EOF
chmod 644 "$UNIT"

if [[ $FIREWALL -eq 1 ]]; then
    [[ -n "$OLD_PORT" && "$OLD_PORT" != "$PORT" ]] && firewallClose "$OLD_PORT"
    firewallOpen "$PORT"
fi

systemctl daemon-reload
systemctl enable --quiet "$NAME"
if [[ $WAS_RUNNING -eq 1 ]]; then
    say "restarting (running games on this server end now)"
    systemctl restart "$NAME"
else
    systemctl start "$NAME"
fi

# --- Does it answer? --------------------------------------------------------------
ok=0
for _ in $(seq 1 20); do
    if "$INSTALL_DIR/fitzelserver" --probe "127.0.0.1:$PORT" >/dev/null 2>&1; then ok=1; break; fi
    sleep 0.25
done
if [[ $ok -ne 1 ]]; then
    warn "the server does not answer on port $PORT -- its log:"
    journalctl -u "$NAME" -n 20 --no-pager >&2 || true
    exit 1
fi

ADDRS="$(hostname -I 2>/dev/null | tr ' ' '\n' | grep -v -e '^$' -e ':' | tr '\n' ' ' || true)"
say "Steelwars server running on port $PORT ($TURN_MS ms turns, up to $MAX_CLIENTS connections)"
cat <<EOF

  In Steelwars: Netzwerkspiel -> Server: ${ADDRS:-<address of this machine>}  Port: $PORT
  (a cloud provider's own firewall / security group must let TCP $PORT in too)

  From anywhere:   $INSTALL_DIR/fitzelserver --probe <address>:$PORT
  Log:             journalctl -u $NAME -f
  Status:          systemctl status $NAME
  Settings:        $CONF, then: systemctl restart $NAME
  Remove:          sudo $HERE/setup.sh --uninstall

EOF
