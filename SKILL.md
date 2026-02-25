---
name: gam-cli
description: Work with the GAM CLI (Google Ad Manager Command Line Tool). Use when modifying gam-cli, extending commands, debugging Ad Manager API integration, or understanding orders, line items, inventory forecasts, and report metrics.
---

# GAM CLI Development

## Overview

GAM CLI is a Python tool for Google Ad Manager. Main entry: `gam-cli.py`. Config lives at `~/.gam-cli/config.yaml`.

## Architecture

- **SOAP API** (`googleads`): UserService, OrderService, LineItemService, NetworkService, CreativeService, ForecastService
- **REST API** (`google.ads.admanager_v1`): ReportServiceClient for impressions/clicks (requires `path_to_private_key_file`)
- **Config**: YAML with `ad_manager.network_code`, `ad_manager.path_to_private_key_file`

## Key Structures

### Config Format

```yaml
ad_manager:
  application_name: "GAM App CLI"
  network_code: "127377506"
  path_to_private_key_file: "creds.json"  # relative to cwd or absolute
```

### CLI Option Parsing

`parse_opts(args)` extracts: `config`, `limit`, `order_id`, `preset`, `start`, `end`, `status`, `metrics_range`, `json`, `debug`.

`--metrics-range` supports: `30d`, `90d`, `365d`, `mtd`, `ytd` (default: `365d`).

### Inventory Presets

`INVENTORY_PRESETS`: `run-of-site` (all sizes), `desktop` (970x250, 300x250, etc.), `mobile` (320x50, etc.).

### Order Status Mapping

`ORDER_STATUS_MAP` maps CLI aliases (e.g. `delivering`, `approved`) to GAM status strings (e.g. `APPROVED`).

### Metrics Range Mapping

`METRICS_RANGE_MAP` maps CLI values to GAM relative ranges:

- `30d` -> `LAST_30_DAYS`
- `90d` -> `LAST_90_DAYS`
- `365d` -> `LAST_365_DAYS`
- `mtd` -> `MONTH_TO_DATE`
- `ytd` -> `YEAR_TO_DATE`

## Adding New Commands

1. Implement method in `GAMService` (e.g. `get_xxx()`).
2. Add `elif cmd == "xxx":` in `main()` with output handling (table or JSON).
3. Add option parsing in `parse_opts()` if needed.
4. Update module docstring and README.

## Data Helpers

- `_attr(obj, key, default)` — Safe attribute access for SOAP/dict objects
- `_format_datetime(obj)` — GAM DateTime → `YYYY-MM-DD`
- `parse_date(s)` — Parses `YYYY-MM-DD` or `DDMMYYYY`
- `format_table(headers, rows)` — Prints aligned table
- `line-items` table includes a `Goal` column (goal units + unit type)

## Error Handling

- `log_error()`, `exit_with_error()` — Write to `~/.gam-cli/errors.log`
- Set `GAM_DEBUG=1` for tracebacks when report/metrics fail

## Testing

```bash
gam user          # Quick connectivity check
gam orders -l 1   # Minimal data fetch
gam orders --metrics-range ytd -l 1
gam line-items --order-id 12345 --metrics-range 90d
GAM_DEBUG=1 gam orders  # Debug report/metrics
```
