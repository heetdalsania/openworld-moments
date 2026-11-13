#!/usr/bin/env bash
# SPDX-License-Identifier: AGPL-3.0-or-later
# M34: build FFmpeg and FFprobe for one macOS architecture from the same pinned,
# checksum-verified sources as Windows (scripts/windows/sources.json, ADR-0007).
#
#   uv run --directory services/media-worker python ../../scripts/windows/prepare-sources.py
#   bash scripts/macos/build-media.sh arm64     # or x86_64; on a native Mac of that arch
#
# Static FFmpeg libraries, libx264 the only external codec, autodetection off (so no
# VideoToolbox, AudioToolbox, Secure Transport, zlib or iconv): the executables link
# only libSystem and run on macOS 14+. No user media is processed.
set -euo pipefail
arch="${1:?usage: build-media.sh arm64|x86_64}"
case "$arch" in
  arm64) host="aarch64-apple-darwin"; ffarch="aarch64" ;;
  x86_64) host="x86_64-apple-darwin"; ffarch="x86_64" ;;
  *) echo "unknown architecture: $arch" >&2; exit 2 ;;
esac
if [ "$(uname -s)" != "Darwin" ] || [ "$(uname -m)" != "$arch" ]; then
  echo "build $arch media tools on a native $arch Mac" >&2
  exit 2
fi
if [ "$arch" = "x86_64" ] && ! command -v nasm >/dev/null; then
  echo "nasm is required for x86_64 assembly (brew install nasm)" >&2
  exit 2
fi
project_root="$(pwd)"
work="$project_root/output/packaging/source-build"
prefix="$project_root/output/packaging/toolchain-$arch"
out="$project_root/output/packaging/media"
minimum="14.0"
flags="-arch $arch -mmacosx-version-min=$minimum"
export SOURCE_DATE_EPOCH="${SOURCE_DATE_EPOCH:-0}"
export MACOSX_DEPLOYMENT_TARGET="$minimum"
export PKG_CONFIG_PATH="$prefix/lib/pkgconfig"
export PKG_CONFIG_LIBDIR="$prefix/lib/pkgconfig"   # never pick up Homebrew libraries
rm -rf "$prefix"

cd "$work/x264"
make distclean >/dev/null 2>&1 || true
./configure --prefix="$prefix" --host="$host" --enable-static --disable-cli \
  --bit-depth=8 --extra-cflags="$flags" --extra-ldflags="-arch $arch -mmacosx-version-min=$minimum"
make -j"$(sysctl -n hw.logicalcpu)"
make install

cd "$work/ffmpeg"
make distclean >/dev/null 2>&1 || true
# FFmpeg embeds its configure line in the binaries. Keep it free of build-machine paths
# (M30 artifact scan): a placeholder install prefix (nothing is installed) and paths
# relative to this source tree. Sources compile in-tree with relative names.
toolchain="../../toolchain-$arch"
./configure --prefix=/opt/openworld-moments-unused --target-os=darwin --arch="$ffarch" --cc=clang \
  --disable-autodetect --disable-network --disable-doc --disable-debug \
  --disable-shared --enable-static --enable-gpl --enable-libx264 --disable-ffplay \
  --pkg-config-flags=--static \
  --extra-cflags="-I$toolchain/include $flags" \
  --extra-ldflags="-L$toolchain/lib -arch $arch -mmacosx-version-min=$minimum"
make -j"$(sysctl -n hw.logicalcpu)"

mkdir -p "$out"
cp ffmpeg ffprobe "$out/"
{
  clang --version | head -1
  echo "SDK $(xcrun --show-sdk-version)"
  echo "MACOSX_DEPLOYMENT_TARGET=$minimum"
} > "$out/compiler.txt"
{
  echo "pkgconf $(pkg-config --version)"
  if command -v nasm >/dev/null; then nasm -v; fi
} > "$out/build-packages.txt"
echo "built $arch ffmpeg and ffprobe in output/packaging/media"
