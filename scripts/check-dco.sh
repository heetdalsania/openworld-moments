#!/usr/bin/env bash
# SPDX-License-Identifier: AGPL-3.0-or-later
# Verify that every non-merge commit in BASE..HEAD carries a DCO sign-off
# matching its author. Usage: scripts/check-dco.sh <base-ref> [head-ref]
set -euo pipefail

base="${1:?usage: check-dco.sh <base-ref> [head-ref]}"
head="${2:-HEAD}"
failed=0

for sha in $(git rev-list --no-merges "${base}..${head}"); do
  author="$(git log -1 --format='%an <%ae>' "$sha")"
  if ! git log -1 --format='%(trailers:key=Signed-off-by,valueonly)' "$sha" | grep -Fqx "$author"; then
    echo "::error::Commit ${sha:0:12} is missing 'Signed-off-by: ${author}'"
    failed=1
  fi
done

if [ "$failed" -ne 0 ]; then
  echo "Sign off commits with 'git commit -s'. See CONTRIBUTING.md (Developer Certificate of Origin)."
  exit 1
fi
echo "All commits are signed off."
