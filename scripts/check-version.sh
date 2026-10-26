#!/bin/bash
# On a v* tag, the tag must equal .claude-plugin/plugin.json's version: the
# engine image and the plugin are versioned together.
set -euo pipefail

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ref="${GITHUB_REF:-}"
case "$ref" in
  refs/tags/v*) ;;
  *) exit 0 ;;
esac
tag="${ref#refs/tags/v}"
version="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["version"])' "$root/.claude-plugin/plugin.json")"
if [ "$tag" != "$version" ]; then
  echo "tag v$tag does not match plugin.json version $version" >&2
  exit 1
fi
