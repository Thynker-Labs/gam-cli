# GAM CLI

Google Ad Manager CLI - Manage orders, line items, creatives, and networks from the command line.

## Installation

```bash
npm install -g @thynker-labs/gam-cli
```

## Configuration

Create a `gam.yaml` config file:

```yaml
ad_manager:
  application_name: "Your App Name"
  network_code: "YOUR_NETWORK_CODE"
  path_to_private_key_file: "/path/to/service-account.json"
```

Then initialize:

```bash
gam init gam.yaml
```

## Usage

```bash
# Show current user info
gam user

# List orders
gam orders --limit 20

# Filter orders by status
gam orders --status APPROVED

# List line items
gam line-items --limit 10

# Filter line items by order
gam line-items --order-id 12345

# List available networks
gam networks

# List creatives
gam creatives --limit 20

# Output as JSON
gam orders --json
gam networks --json
```

## Options

- `--limit, -l <num>` - Limit number of results (default: 10)
- `--order-id <id>` - Filter by order ID (for line-items)
- `--status <status>` - Filter by status (for orders, e.g., APPROVED, DRAFT, PAUSED)
- `--json` - Output as JSON

## Commands

| Command | Description |
|---------|-------------|
| `gam init <config>` | Initialize with GAM config file |
| `gam user` | Show current user info |
| `gam orders` | List orders |
| `gam line-items` | List line items |
| `gam networks` | List available networks |
| `gam creatives` | List creatives |

## Config Location

Default config is stored at: `~/.gam-cli/config.yaml`

## Error Logs

Errors are logged to: `~/.gam-cli/errors.log`
