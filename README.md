# GAM CLI

A lightweight command-line tool for **Google Ad Manager** (GAM). Query orders, line items, inventory forecasts, networks, and creatives directly from your terminal.

---

## Features

| Command | Description |
|---------|-------------|
| `gam init` | Initialize configuration from a YAML file |
| `gam user` | Show current user and connection info |
| `gam orders` | List orders with impressions, clicks, and status |
| `gam line-items` | List line items with optional order filter |
| `gam inventory` | Show inventory forecast (available, forecasted, reserved) |
| `gam networks` | List available Ad Manager networks |
| `gam creatives` | List creatives |

Supports **JSON output**, **date filters**, **inventory presets** (run-of-site, desktop, mobile), and **status filters** for orders.

---

## Quick Start

### 1. Install

**Linux / macOS** — use the install script:

```bash
curl -fsSL https://raw.githubusercontent.com/Thynker-Labs/gam-cli/main/install.sh | sh
```

Or clone and run locally:

```bash
git clone https://github.com/Thynker-Labs/gam-cli.git
cd gam-cli
./install.sh
```

See [Installation](#installation) for manual install and other options.

### 2. Configure

Create a `gam.yaml` (or similar) with your Ad Manager credentials:

```yaml
ad_manager:
  application_name: "GAM App CLI"
  network_code: "YOUR_NETWORK_CODE"
  path_to_private_key_file: "path/to/creds.json"
```

Then initialize:

```bash
gam init gam.yaml
```

### 3. Run

```bash
gam user
gam orders --limit 20
gam inventory --start 2026-02-24 --end 2026-03-10
```

---

## Installation

### Option A: Install Script (Linux / macOS)

Run `./install.sh` from the project directory. It will:

- Ensure Python 3.7+ is available
- Create a virtual environment in `~/.local/gam-cli`
- Install dependencies from `requirements.txt`
- Create a `gam` launcher in `~/.local/bin` (or `~/bin` if preferred)
- Add the bin directory to your shell config if needed

```bash
# From the project directory
./install.sh

# Custom install prefix (default: ~/.local)
./install.sh --prefix /opt/gam-cli
```

The `gam` launcher is placed in `~/.local/bin` and added to `PATH` in your shell config if possible. Restart your terminal or run `source ~/.bashrc` (or `~/.zshrc`) to apply.

### Option B: Manual Installation

1. **Clone the repository**

   ```bash
   git clone https://github.com/YOUR_USER/gam-cli.git
   cd gam-cli
   ```

2. **Create a virtual environment (recommended)**

   ```bash
   python3 -m venv .venv
   source .venv/bin/activate   # Linux/macOS
   # .venv\Scripts\activate    # Windows
   ```

3. **Install dependencies**

   ```bash
   pip install -r requirements.txt
   ```

4. **Add `gam` to your PATH**

   - Symlink:
     ```bash
     ln -sf "$(pwd)/gam-cli.py" ~/.local/bin/gam
     chmod +x ~/.local/bin/gam
     ```
   - Or add an alias to `~/.bashrc` / `~/.zshrc`:
     ```bash
     alias gam='python3 /path/to/gam-cli/gam-cli.py'
     ```

### Option C: Pip (global or user)

```bash
pip install --user googleads PyYAML google-ads-admanager
# Then add gam-cli.py to PATH or create a wrapper script
```

---

## Configuration

### Config File

By default, GAM CLI reads from `~/.gam-cli/config.yaml`. Set this up with:

```bash
gam init /path/to/your/gam.yaml
```

### Config Format

```yaml
ad_manager:
  application_name: "GAM App CLI"      # Optional, for logging
  network_code: "127377506"            # Your Ad Manager network code
  path_to_private_key_file: "creds.json"  # Path to service account JSON (relative to cwd or absolute)
```

### Service Account Setup

1. Create a service account in [Google Cloud Console](https://console.cloud.google.com/iam-admin/serviceaccounts).
2. Download the JSON key and save it (e.g. `creds.json`).
3. Grant the service account access to your Ad Manager network.
4. Use the path to that file in `path_to_private_key_file`.
5. For **reporting** (impressions/clicks), the same credentials are used via the Ad Manager REST API.

### Using a Different Config

```bash
gam --config /path/to/config.yaml user
gam -c ~/work-gam.yaml orders
```

---

## Usage

### Commands

| Command | Description |
|---------|-------------|
| `gam init <file>` | Copy config to `~/.gam-cli/config.yaml` |
| `gam user` | Current user info |
| `gam orders` | List orders |
| `gam line-items` | List line items |
| `gam inventory` | Inventory forecast |
| `gam networks` | List networks |
| `gam creatives` | List creatives |

### Options

| Option | Description |
|--------|-------------|
| `--config`, `-c` | Config file path (default: `~/.gam-cli/config.yaml`) |
| `--limit`, `-l` | Limit number of results (default: 10) |
| `--order-id` | Filter line items by order ID |
| `--preset` | Inventory preset: `run-of-site`, `desktop`, `mobile` |
| `--start` | Start date (`YYYY-MM-DD` or `DDMMYYYY`) |
| `--end` | End date |
| `--status` | Filter orders by status |
| `--json` | Output as JSON |
| `--debug` | Show debug info |

### Order Status Values

`delivering`, `approved`, `active`, `draft`, `pending_approval`, `disapproved`, `paused`, `canceled`, `deleted`

### Examples

```bash
# User info
gam user

# Orders
gam orders --limit 20
gam orders --status delivering --json

# Line items
gam line-items
gam line-items --order-id 12345 --limit 50

# Inventory
gam inventory
gam inventory --preset mobile --start 2026-02-24 --end 2026-03-10

# Networks & creatives
gam networks
gam creatives --limit 20 --json
```

---

## File Locations

| Path | Purpose |
|------|---------|
| `~/.gam-cli/config.yaml` | Main config (set via `gam init`) |
| `~/.gam-cli/errors.log` | Error log for debugging |

---

## Troubleshooting

### `gam: command not found`

- Run `./install.sh` and ensure `~/.local/bin` is in your `PATH`.
- Or use: `python3 /path/to/gam-cli/gam-cli.py` instead of `gam`.

### `No config found`

```bash
gam init /path/to/your/gam.yaml
```

### Metrics show 0 (impressions/clicks)

- Ensure `path_to_private_key_file` points to a valid service account JSON.
- The path can be relative to the current working directory or absolute.
- Set `GAM_DEBUG=1` for more detail: `GAM_DEBUG=1 gam orders`.

### Authentication errors

- Verify network code and service account.
- Confirm the service account has access to the Ad Manager network.
- Check `~/.gam-cli/errors.log` for details.

---

## Requirements

- **Python 3.7+**
- **Dependencies**: `googleads`, `PyYAML`, `google-ads-admanager` (see `requirements.txt`)

---

## License

MIT (or as specified in the project).
