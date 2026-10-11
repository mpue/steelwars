#!/usr/bin/env bash
# STEELWARS -- builds the dedicated server package for Linux.
#
# The server is Fitzel's lockstep relay (fitzelserver, sandbox/tools in the
# engine): it paces the turns and passes the orders on; the game itself runs in
# the players' clients. Built here fully static, so the one binary runs on any
# x86_64 Linux whatever its C library; the sources ride along, and setup.sh
# builds from them on a machine the binary does not fit (an ARM server).
#
#   server/build.sh                 -> server/dist/steelwars-server-linux-x86_64.tar.gz
#   FITZEL_DIR=/path/to/fitzel server/build.sh
#
# Copy the archive to the server, unpack it, run `sudo ./setup.sh` there.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
FITZEL_DIR="${FITZEL_DIR:-$HERE/../../devel/fitzel}"
SRC="$FITZEL_DIR/sandbox"
CXX="${CXX:-g++}"
ARCH="$(uname -m)"
NAME="steelwars-server"
DIST="$HERE/dist"

for f in tools/fitzelserver.cpp tools/netcheck.cpp src/NetRelay.cpp src/NetRelay.hpp src/NetSocket.cpp src/NetSocket.hpp; do
    [[ -f "$SRC/$f" ]] || { echo "build.sh: $SRC/$f not found -- set FITZEL_DIR to the engine checkout" >&2; exit 1; }
done
command -v "$CXX" >/dev/null || { echo "build.sh: no C++ compiler ($CXX)" >&2; exit 1; }

WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT
PKG="$WORK/$NAME"
mkdir -p "$PKG/bin" "$PKG/src"

echo "== compiling (static, $ARCH)"
FLAGS=(-std=c++17 -O2 -I"$SRC/src")
# The one warning a static glibc gives (getaddrinfo, used only by --probe with
# a host name) is expected; anything else is shown.
"$CXX" "${FLAGS[@]}" -static -s "$SRC/tools/fitzelserver.cpp" "$SRC/src/NetRelay.cpp" "$SRC/src/NetSocket.cpp" \
    -o "$PKG/bin/fitzelserver" 2>&1 | grep -v -e "getaddrinfo" -e "In Funktion" -e "in function" || true
[[ -x "$PKG/bin/fitzelserver" ]] || { echo "build.sh: compile failed" >&2; exit 1; }

echo "== testing the relay (netcheck)"
"$CXX" "${FLAGS[@]}" "$SRC/tools/netcheck.cpp" "$SRC/src/NetRelay.cpp" "$SRC/src/NetSocket.cpp" -o "$WORK/netcheck"
"$WORK/netcheck" | tail -1
"$WORK/netcheck" >/dev/null

echo "== testing the binary"
PORT=$((30000 + RANDOM % 20000))
"$PKG/bin/fitzelserver" --port "$PORT" --quiet >/dev/null &
PID=$!
sleep 0.3
"$PKG/bin/fitzelserver" --probe "127.0.0.1:$PORT"
kill -TERM "$PID"
wait "$PID"

cp "$SRC/tools/fitzelserver.cpp" "$SRC/src/NetRelay.cpp" "$SRC/src/NetRelay.hpp" \
   "$SRC/src/NetSocket.cpp" "$SRC/src/NetSocket.hpp" "$PKG/src/"
cp "$HERE/setup.sh" "$PKG/setup.sh"
chmod +x "$PKG/setup.sh"
{
    echo "steelwars-server built $(date -u +%Y-%m-%dT%H:%MZ) for linux-$ARCH"
    echo "fitzel    $(git -C "$FITZEL_DIR" describe --always --dirty 2>/dev/null || echo unknown)"
    echo "steelwars $(git -C "$HERE/.." describe --always --dirty 2>/dev/null || echo unknown)"
} > "$PKG/VERSION"

mkdir -p "$DIST"
OUT="$DIST/$NAME-linux-$ARCH.tar.gz"
tar -C "$WORK" -czf "$OUT" "$NAME"
echo "== $OUT ($(du -h "$OUT" | cut -f1))"
echo "   on the server:  tar xzf $(basename "$OUT") && cd $NAME && sudo ./setup.sh"
