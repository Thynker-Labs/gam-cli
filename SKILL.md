# SKILL.md - GAM CLI Skill

## Overview

This skill provides a CLI for Google Ad Manager (GAM) operations.

## Requirements

- Node.js 18+
- npm or yarn
- Google Ad Manager service account credentials

## Installation

```bash
cd gam-cli
npm install
npm link
```

## Configuration

Create a `gam.yaml` file:

```yaml
ad_manager:
  application_name: "Your App Name"
  network_code: "YOUR_NETWORK_CODE"
  path_to_private_key_file: "/path/to/service-account.json"
```

Initialize:

```bash
gam init gam.yaml
```

## Commands

| Command | Description |
|---------|-------------|
| `gam user` | Show current GAM user |
| `gam orders` | List orders |
| `gam line-items` | List line items |
| `gam networks` | List available networks |
| `gam creatives` | List creatives |

## Examples

```bash
# Check connection
gam user

# List recent orders
gam orders -l 20

# Get line items for specific order
gam line-items --order-id 123456

# Get all networks
gam networks --json
```

## Options

- `-l, --limit <num>` - Limit results
- `--order-id <id>` - Filter by order ID
- `--status <status>` - Filter by status
- `--json` - JSON output

## Troubleshooting

Check error logs at: `~/.gam-cli/errors.log`
