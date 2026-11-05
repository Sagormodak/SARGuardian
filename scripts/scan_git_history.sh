#!/usr/bin/env bash
set -euo pipefail
work_dir="$(mktemp -d)"
trap 'rm -rf "$work_dir"' EXIT
archive="gitleaks_8.30.1_linux_x64.tar.gz"
curl -fsSL "https://github.com/gitleaks/gitleaks/releases/download/v8.30.1/$archive" -o "$work_dir/$archive"
echo "551f6fc83ea457d62a0d98237cbad105af8d557003051f41f3e7ca7b3f2470eb  $work_dir/$archive" | sha256sum --check --status
tar -xzf "$work_dir/$archive" -C "$work_dir" gitleaks
"$work_dir/gitleaks" git --redact=100 --no-banner --log-opts=--all .
