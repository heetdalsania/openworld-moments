#!/usr/bin/env bash
# SPDX-License-Identifier: AGPL-3.0-or-later
# Run in native MSYS2 MINGW64 after prepare-sources.py. No user media is processed.
set -euo pipefail
project_root="$(pwd)"
prefix="$project_root/output/packaging/toolchain"
export SOURCE_DATE_EPOCH="${SOURCE_DATE_EPOCH:-0}"
export PKG_CONFIG_PATH="$prefix/lib/pkgconfig"
cd output/packaging/source-build/x264
./configure --prefix="$prefix" --enable-static --disable-cli --bit-depth=8 \
  --extra-cflags="-ffile-prefix-map=$project_root=." \
  --extra-ldflags="-Wl,--no-insert-timestamp"
make -j4
make install
cd ../ffmpeg
./configure --prefix="$prefix" --target-os=mingw32 --arch=x86_64 \
  --disable-autodetect --disable-network --disable-doc --disable-debug \
  --disable-shared --enable-static --enable-gpl --enable-libx264 --disable-ffplay \
  --pkg-config-flags=--static --extra-cflags="-I$prefix/include -ffile-prefix-map=$project_root=." \
  --extra-ldflags="-L$prefix/lib -static -Wl,--no-insert-timestamp"
make -j4
mkdir -p "$project_root/output/packaging/media"
cp ffmpeg.exe ffprobe.exe "$project_root/output/packaging/media/"
cp ffbuild/config.log "$project_root/output/packaging/media/config.log"
gcc --version > "$project_root/output/packaging/media/compiler.txt"
pacman -Q > "$project_root/output/packaging/media/build-packages.txt"
# Include static-runtime exceptions and the compiler/toolchain license inventory.
cp -R /mingw64/share/licenses "$project_root/output/packaging/media/toolchain-notices"
