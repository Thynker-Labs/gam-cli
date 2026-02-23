#!/usr/bin/env sh
#
# Bootstrap: clone gam-cli and run install.sh
# Usage: curl -fsSL https://raw.githubusercontent.com/USER/gam-cli/main/get-gam.sh | sh
#
# Set GAM_CLI_REPO to override the default repo (e.g. https://github.com/you/gam-cli.git)
#
set -e

REPO="${GAM_CLI_REPO:-https://github.com/Thynker-Labs/gam-cli.git}"
CLONE_DIR="${HOME}/.gam-cli-src"

echo "Cloning gam-cli from ${REPO}..."
rm -rf "${CLONE_DIR}"
git clone --depth 1 "${REPO}" "${CLONE_DIR}"

echo "Running installer..."
exec sh "${CLONE_DIR}/install.sh" "$@"
