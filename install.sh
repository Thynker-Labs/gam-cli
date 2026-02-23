#!/usr/bin/env sh
#
# GAM CLI Installer for Linux and macOS
#
# Usage:
#   ./install.sh              # Install to ~/.local
#   ./install.sh --prefix DIR  # Install to custom directory
#
# Must be run from the gam-cli project directory (containing gam-cli.py and requirements.txt).
#
set -e

# Resolve script directory (handles symlinks); fallback to cwd if $0 is sh (e.g. curl | sh)
if [ -f "$0" ] && [ -r "$0" ]; then
  SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
else
  SCRIPT_DIR="$(pwd)"
fi

# Validate project directory; if missing, clone and re-exec (bootstrap for "curl | sh")
if [ ! -f "${SCRIPT_DIR}/requirements.txt" ] || [ ! -f "${SCRIPT_DIR}/gam-cli.py" ]; then
  REPO="${GAM_CLI_REPO:-https://github.com/Thynker-Labs/gam-cli.git}"
  CLONE_DIR="${HOME}/.gam-cli-src"
  echo "Project files not found. Cloning from ${REPO}..."
  if command -v git >/dev/null 2>&1; then
    rm -rf "${CLONE_DIR}"
    git clone --depth 1 "${REPO}" "${CLONE_DIR}"
    exec "${CLONE_DIR}/install.sh" "$@"
  fi
  echo "Error: Must run install.sh from the gam-cli project directory."
  echo "  cd /path/to/gam-cli && ./install.sh"
  echo "Or: git clone https://github.com/Thynker-Labs/gam-cli.git && cd gam-cli && ./install.sh"
  exit 1
fi

INSTALL_PREFIX="${HOME}/.local"
while [ $# -gt 0 ]; do
  case "$1" in
    --prefix=*)
      INSTALL_PREFIX="${1#*=}"
      shift
      ;;
    --prefix)
      shift
      [ -n "$1" ] && INSTALL_PREFIX="$1"
      shift
      ;;
    *)
      shift
      ;;
  esac
done

VENV_DIR="${INSTALL_PREFIX}/gam-cli"
BIN_DIR="${INSTALL_PREFIX}/bin"
GAM_SCRIPT="${BIN_DIR}/gam"

echo "GAM CLI Installer"
echo "================="
echo "Script dir:   ${SCRIPT_DIR}"
echo "Install to:   ${INSTALL_PREFIX}"
echo "Virtual env:  ${VENV_DIR}"
echo "Binary:       ${GAM_SCRIPT}"
echo ""

# Check Python 3
if ! command -v python3 >/dev/null 2>&1; then
  echo "Error: python3 not found. Please install Python 3.7 or later."
  exit 1
fi

PYTHON_CMD="python3"
PYTHON_VERSION=$(${PYTHON_CMD} -c 'import sys; v=sys.version_info; print(f"{v.major}.{v.minor}")' 2>/dev/null || echo "0")
PY_MAJOR=$(${PYTHON_CMD} -c 'import sys; print(sys.version_info.major)' 2>/dev/null)
PY_MINOR=$(${PYTHON_CMD} -c 'import sys; print(sys.version_info.minor)' 2>/dev/null)

if [ "${PY_MAJOR}" -lt 3 ] || { [ "${PY_MAJOR}" -eq 3 ] && [ "${PY_MINOR}" -lt 7 ]; }; then
  echo "Error: Python 3.7+ required. Found: ${PYTHON_VERSION}"
  exit 1
fi

echo "Using Python: $(${PYTHON_CMD} --version)"

# Create directories
mkdir -p "${VENV_DIR}"
mkdir -p "${BIN_DIR}"

# Create virtual environment
echo ""
echo "Creating virtual environment..."
"${PYTHON_CMD}" -m venv "${VENV_DIR}"

# Activate and install
. "${VENV_DIR}/bin/activate"

echo "Installing dependencies..."
pip install --quiet --upgrade pip
pip install --quiet -r "${SCRIPT_DIR}/requirements.txt"

# Copy gam-cli.py into venv for a self-contained install
cp "${SCRIPT_DIR}/gam-cli.py" "${VENV_DIR}/"
VENV_PYTHON="${VENV_DIR}/bin/python"

# Create gam launcher script
echo "Creating gam launcher..."
cat > "${GAM_SCRIPT}" << EOF
#!/usr/bin/env sh
# GAM CLI launcher
exec "${VENV_PYTHON}" "${VENV_DIR}/gam-cli.py" "\$@"
EOF

chmod +x "${GAM_SCRIPT}"

# Ensure BIN_DIR is in PATH
SHELL_RC=""
if [ -n "${ZSH_VERSION}" ] || [ -f "${HOME}/.zshrc" ]; then
  SHELL_RC="${HOME}/.zshrc"
elif [ -f "${HOME}/.bashrc" ]; then
  SHELL_RC="${HOME}/.bashrc"
elif [ -f "${HOME}/.profile" ]; then
  SHELL_RC="${HOME}/.profile"
fi

if [ -n "${SHELL_RC}" ]; then
  if grep -q "${BIN_DIR}" "${SHELL_RC}" 2>/dev/null; then
    echo ""
    echo "✓ ${BIN_DIR} already in PATH (in ${SHELL_RC})"
  else
    echo "" >> "${SHELL_RC}"
    echo "# GAM CLI" >> "${SHELL_RC}"
    echo "export PATH=\"\${PATH}:${BIN_DIR}\"" >> "${SHELL_RC}"
    echo ""
    echo "✓ Added ${BIN_DIR} to PATH in ${SHELL_RC}"
  fi
else
  echo ""
  echo "Note: Could not auto-add to PATH. Add this to your shell config:"
  echo "  export PATH=\"\${PATH}:${BIN_DIR}\""
fi

echo ""
echo "Installation complete!"
echo ""
echo "Run 'gam' (you may need to open a new terminal or run 'source ${SHELL_RC:-~/.profile}'):"
echo "  gam init gam.yaml"
echo "  gam user"
echo "  gam orders"
echo ""
