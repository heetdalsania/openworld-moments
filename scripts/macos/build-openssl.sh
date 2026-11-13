#!/usr/bin/env bash
# SPDX-License-Identifier: AGPL-3.0-or-later
# M34: a static OpenSSL for macOS 14+, from the pinned, checksum-verified LTS release in
# scripts/macos/openssl.json. Used only where cryptography has no wheel (Intel Macs):
# Homebrew's OpenSSL targets the build Mac's macOS release, which the Mach-O audit
# rejects, and must never end up linked dynamically outside the app.
#
#   bash scripts/macos/build-openssl.sh x86_64     # prints the prefix to use as OPENSSL_DIR
set -euo pipefail
arch="${1:?usage: build-openssl.sh arm64|x86_64}"
case "$arch" in
  arm64) target="darwin64-arm64-cc" ;;
  x86_64) target="darwin64-x86_64-cc" ;;
  *) echo "unknown architecture: $arch" >&2; exit 2 ;;
esac
project_root="$(pwd)"
pins="$project_root/scripts/macos/openssl.json"
read_pin() { /usr/bin/python3 -c "import json,sys;print(json.load(open(sys.argv[1]))[sys.argv[2]])" "$pins" "$1"; }
version="$(read_pin version)"
url="$(read_pin url)"
sha256="$(read_pin sha256)"
archive="$project_root/output/packaging/sources/$(read_pin archive)"
prefix="$project_root/output/packaging/openssl-$arch"
work="$project_root/output/packaging/source-build/openssl-$arch"
mkdir -p "$(dirname "$archive")"
if [ ! -f "$archive" ]; then
  curl --proto '=https' --tlsv1.2 -sSfL --max-filesize 104857600 -o "$archive" "$url"
fi
echo "$sha256  $archive" | shasum -a 256 -c - >/dev/null
rm -rf "$work" "$prefix"
mkdir -p "$work"
tar -xzf "$archive" -C "$work" --strip-components 1 --no-same-owner
cd "$work"
export MACOSX_DEPLOYMENT_TARGET="14.0"
./Configure "$target" no-shared no-tests no-docs no-apps \
  --prefix="$prefix" --openssldir=/private/etc/ssl --libdir=lib \
  -mmacosx-version-min=14.0 >/dev/null
make -j"$(sysctl -n hw.logicalcpu)" >/dev/null
make install_sw >/dev/null
cp LICENSE.txt "$prefix/LICENSE.txt"
echo "$prefix"
echo "built static OpenSSL $version for $arch (macOS 14+)" >&2
