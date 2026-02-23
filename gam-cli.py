#!/usr/bin/env python3
"""
GAM CLI - Google Ad Manager Command Line Tool

Usage:
  gam init <config.yaml>     Initialize with GAM config file
  gam user                  Show current user info
  gam orders                List orders
  gam line-items            List line items
  gam inventory             Show available inventory (forecast)
  gam networks              List available networks
  gam creatives             List creatives

Options:
  --config, -c <path>       Config file path (default: ~/.gam-cli/config.yaml)
  --limit, -l <num>         Limit number of results
  --order-id <id>           Filter by order ID (for line-items)
  --preset <name>           Inventory preset: run-of-site, desktop, mobile
  --start <date>            Start date (DDMMYYYY or YYYY-MM-DD)
  --end <date>              End date (DDMMYYYY or YYYY-MM-DD)
  --status <status>         Filter by status (for orders)
  --json                    Output as JSON
  --debug                   Show debug info (for troubleshooting)

Examples:
  gam init gam.yaml
  gam user
  gam orders --limit 20
  gam line-items --order-id 12345
  gam inventory --start 2026-02-24 --end 2026-03-10
  gam networks
  gam creatives --json
"""
import json
import os
import sys
import shutil
import yaml
import datetime
from googleads import ad_manager

# --- Constants & Setup ---
CONFIG_DIR = os.path.join(os.path.expanduser("~"), ".gam-cli")
CONFIG_FILE = os.path.join(CONFIG_DIR, "config.yaml")
ERROR_LOG_FILE = os.path.join(CONFIG_DIR, "errors.log")

# Order status mapping (SOAP returns string names)
ORDER_STATUS_MAP = {
    "delivering": "APPROVED",
    "approved": "APPROVED",
    "active": "APPROVED",
    "draft": "DRAFT",
    "pending_approval": "PENDING_APPROVAL",
    "disapproved": "DISAPPROVED",
    "paused": "PAUSED",
    "canceled": "CANCELED",
    "cancelled": "CANCELED",
    "deleted": "DELETED",
}

# Inventory presets: run-of-site (all), desktop banners, mobile banners
INVENTORY_PRESETS = {
    "run-of-site": {
        "label": "Run of site (all sites)",
        "sizes": None,  # No size filter = all
    },
    "desktop": {
        "label": "Desktop banners",
        "sizes": [
            {"width": 970, "height": 250, "isAspectRatio": False},
            {"width": 300, "height": 250, "isAspectRatio": False},
            {"width": 300, "height": 600, "isAspectRatio": False},
            {"width": 728, "height": 90, "isAspectRatio": False},
        ],
    },
    "mobile": {
        "label": "Mobile banners",
        "sizes": [
            {"width": 320, "height": 50, "isAspectRatio": False},
            {"width": 320, "height": 100, "isAspectRatio": False},
            {"width": 300, "height": 50, "isAspectRatio": False},
            {"width": 320, "height": 480, "isAspectRatio": False},
            {"width": 300, "height": 250, "isAspectRatio": False},
            {"width": 728, "height": 90, "isAspectRatio": False},
        ],
    },
}


def ensure_config_dir():
    if not os.path.exists(CONFIG_DIR):
        os.makedirs(CONFIG_DIR, exist_ok=True)


def log_error(error, context="unknown"):
    ensure_config_dir()
    timestamp = datetime.datetime.now().isoformat()
    message = str(error)
    entry = f"[{timestamp}] [{context}] {message}\n"
    with open(ERROR_LOG_FILE, "a") as f:
        f.write(entry)


def exit_with_error(error, context):
    log_error(error, context)
    print(f"Error: {error}")
    print(f"Details logged to: {ERROR_LOG_FILE}")
    sys.exit(1)


def _attr(obj, key, default="N/A"):
    """Get attribute from SOAP object or dict."""
    if obj is None:
        return default
    if hasattr(obj, key):
        val = getattr(obj, key)
        return val if val is not None else default
    if isinstance(obj, dict) and key in obj:
        val = obj[key]
        return val if val is not None else default
    return default


def _format_datetime(obj):
    """Format GAM DateTime object to YYYY-MM-DD string."""
    if obj is None:
        return "-"
    try:
        if hasattr(obj, "date"):
            d = obj.date
            if hasattr(d, "year") and hasattr(d, "month") and hasattr(d, "day"):
                return f"{d.year:04d}-{d.month:02d}-{d.day:02d}"
        if isinstance(obj, dict) and "date" in obj:
            d = obj["date"]
            return f"{d['year']:04d}-{d['month']:02d}-{d['day']:02d}"
    except (TypeError, KeyError):
        pass
    return str(obj)[:10] if obj else "-"


def parse_date(s):
    """Parse date string. Supports YYYY-MM-DD and DDMMYYYY."""
    if not s or not isinstance(s, str):
        return None
    s = s.strip()
    if len(s) == 8 and s.isdigit():  # DDMMYYYY
        try:
            return datetime.datetime(
                int(s[4:8]), int(s[2:4]), int(s[0:2])
            ).date()
        except ValueError:
            return None
    if len(s) >= 10 and s[4] == "-":  # YYYY-MM-DD
        try:
            parts = s[:10].split("-")
            if len(parts) == 3:
                return datetime.datetime(
                    int(parts[0]), int(parts[1]), int(parts[2])
                ).date()
        except (ValueError, IndexError):
            pass
    return None


def parse_opts(args):
    """Parse common CLI options from args list."""
    opts = {
        "limit": 10,
        "order_id": None,
        "preset": None,
        "start": None,
        "end": None,
        "status": None,
        "json": False,
        "debug": False,
    }
    i = 1
    while i < len(args):
        if args[i] in ("--limit", "-l") and i + 1 < len(args):
            opts["limit"] = int(args[i + 1])
            i += 2
        elif args[i] == "--order-id" and i + 1 < len(args):
            opts["order_id"] = args[i + 1]
            i += 2
        elif args[i] == "--preset" and i + 1 < len(args):
            opts["preset"] = args[i + 1]
            i += 2
        elif args[i] == "--start" and i + 1 < len(args):
            opts["start"] = parse_date(args[i + 1])
            i += 2
        elif args[i] == "--end" and i + 1 < len(args):
            opts["end"] = parse_date(args[i + 1])
            i += 2
        elif args[i] == "--status" and i + 1 < len(args):
            opts["status"] = args[i + 1]
            i += 2
        elif args[i] == "--json":
            opts["json"] = True
            i += 1
        elif args[i] == "--debug":
            opts["debug"] = True
            i += 1
        else:
            i += 1
    return opts


# --- Core Service Logic ---
class GAMService:
    def __init__(self, config_path=None):
        path = config_path or CONFIG_FILE
        if not os.path.exists(path):
            print(f"No config found at {path}")
            print("Run with: gam init <path-to-gam.yaml>")
            sys.exit(1)

        with open(path, "r") as f:
            self.raw_config = yaml.safe_load(f)

        self.client = ad_manager.AdManagerClient.LoadFromStorage(path)
        self.network_code = self.raw_config["ad_manager"]["network_code"]

    def get_user(self):
        user_service = self.client.GetService("UserService", version="v202511")
        me = user_service.getCurrentUser()
        return {
            "displayName": _attr(me, "displayName") or _attr(me, "name", ""),
            "email": _attr(me, "email", ""),
            "id": str(_attr(me, "id", "")),
            "roleName": _attr(me, "roleName") or _attr(me, "role", ""),
        }

    def _parse_order_datetime(self, obj):
        """Parse GAM DateTime to timestamp (ms) or None."""
        if obj is None:
            return None
        try:
            if hasattr(obj, "date") and hasattr(obj, "hour"):
                d = obj.date
                h = getattr(obj, "hour", 0) or 0
                if hasattr(d, "year") and hasattr(d, "month") and hasattr(d, "day"):
                    return int(datetime.datetime(
                        d.year, d.month, d.day, h, 0, 0
                    ).timestamp() * 1000)
            if isinstance(obj, dict):
                d = obj.get("date", {})
                h = obj.get("hour", 0) or 0
                if d:
                    return int(datetime.datetime(
                        d.get("year", 1970), d.get("month", 1), d.get("day", 1),
                        h, 0, 0
                    ).timestamp() * 1000)
        except (TypeError, ValueError, KeyError):
            pass
        return None

    def get_orders(self, limit=10, status=None):
        """List orders with optional status filter."""
        order_service = self.client.GetService("OrderService", version="v202511")
        statement = ad_manager.StatementBuilder()
        statement.Where("id > 0")
        statement.OrderBy("id", ascending=False)

        want_delivering = status and status.lower() in ("delivering", "approved", "active")
        if status:
            status_upper = status.upper()
            if status.lower() in ORDER_STATUS_MAP:
                status_upper = ORDER_STATUS_MAP[status.lower()]
            statement.Where(f"status = '{status_upper}'")

        # When filtering for "delivering", we must filter in Python by date range.
        # Fetch more to allow for filtering, then take first `limit`.
        fetch_limit = min(limit * 10, 500) if want_delivering else limit
        statement.Limit(fetch_limit)

        page = order_service.getOrdersByStatement(statement.ToStatement())
        results = getattr(page, "results", None) or []

        now_ms = int(datetime.datetime.now().timestamp() * 1000)
        one_year_ago_ms = now_ms - int(365.25 * 24 * 60 * 60 * 1000)
        orders = []
        for o in results:
            if want_delivering:
                start_ms = self._parse_order_datetime(_attr(o, "startDateTime"))
                end_ms = self._parse_order_datetime(_attr(o, "endDateTime"))
                ul = _attr(o, "unlimitedEndTime") or _attr(o, "unlimited_end_time")
                unlimited = ul in (True, "true", "True", 1)
                if not start_ms or start_ms > now_ms:
                    continue
                if not unlimited and (not end_ms or end_ms < now_ms):
                    continue
                if start_ms < one_year_ago_ms:
                    continue

            order_id = _attr(o, "id")
            raw_status = _attr(o, "status")
            display_status = "DELIVERING" if want_delivering else raw_status
            orders.append({
                "id": order_id,
                "name": (str(_attr(o, "name", "")) or str(_attr(o, "displayName", "")))[:40],
                "status": display_status,
                "startDate": _format_datetime(_attr(o, "startDateTime")),
                "endDate": _format_datetime(_attr(o, "endDateTime")),
                "currency": _attr(o, "currencyCode"),
                "advertiserId": _attr(o, "advertiserId"),
                "impressions": 0,
                "clicks": 0,
            })
            if len(orders) >= limit:
                break

        order_ids = [o["id"] for o in orders if o["id"] != "N/A"]
        if order_ids:
            metrics = self._get_order_metrics(order_ids)
            for o in orders:
                m = metrics.get(str(o["id"]), {})
                o["impressions"] = m.get("impressions", 0)
                o["clicks"] = m.get("clicks", 0)
        return orders

    def get_line_items(self, order_id=None, limit=10):
        """List line items, optionally filtered by order ID."""
        line_item_service = self.client.GetService(
            "LineItemService", version="v202511"
        )
        statement = ad_manager.StatementBuilder()

        if order_id:
            statement.Where(f"orderId = {order_id}")
        else:
            statement.Where("id > 0")

        statement.OrderBy("id", ascending=False)
        statement.Limit(limit)

        page = line_item_service.getLineItemsByStatement(statement.ToStatement())
        results = getattr(page, "results", None) or []

        items = []
        for li in results:
            goal = _attr(li, "primaryGoal")
            goal_units = None
            goal_unit_type = "IMPRESSIONS"
            if goal is not None and goal != "N/A":
                g_units = _attr(goal, "units")
                if g_units is not None and g_units != "N/A":
                    try:
                        goal_units = int(g_units)
                    except (ValueError, TypeError):
                        pass
                g_type = _attr(goal, "unitType")
                if g_type and g_type != "N/A":
                    goal_unit_type = str(g_type)

            items.append({
                "id": _attr(li, "id"),
                "name": (str(_attr(li, "name", "")) or str(_attr(li, "displayName", "")))[:40],
                "orderId": _attr(li, "orderId"),
                "status": _attr(li, "status"),
                "lineItemType": _attr(li, "lineItemType"),
                "startDate": _format_datetime(_attr(li, "startDateTime")),
                "endDate": _format_datetime(_attr(li, "endDateTime")),
                "goalUnits": goal_units,
                "goalUnitType": goal_unit_type,
                "impressions": 0,
                "clicks": 0,
                "ctr": "-",
                "progress": "-",
            })
        line_item_ids = [it["id"] for it in items if it["id"] != "N/A"]
        if line_item_ids:
            metrics = self._get_line_item_metrics(line_item_ids)
            for it in items:
                m = metrics.get(str(it["id"]), {})
                imp = m.get("impressions", 0)
                clk = m.get("clicks", 0)
                it["impressions"] = imp
                it["clicks"] = clk
                it["ctr"] = f"{(clk / imp * 100):.2f}%" if imp > 0 else "-"
                if it["goalUnits"] is not None and it["goalUnits"] > 0:
                    delivered = clk if "CLICKS" in str(it["goalUnitType"]).upper() else imp
                    it["progress"] = f"{(delivered / it['goalUnits'] * 100):.1f}%"
        return items

    def get_networks(self):
        """List available networks."""
        network_service = self.client.GetService(
            "NetworkService", version="v202511"
        )
        networks = network_service.getAllNetworks()
        return [
            {
                "networkCode": _attr(n, "networkCode"),
                "displayName": _attr(n, "displayName"),
                "propertyCode": _attr(n, "propertyCode"),
            }
            for n in networks
        ]

    def get_creatives(self, limit=10):
        """List creatives."""
        creative_service = self.client.GetService(
            "CreativeService", version="v202511"
        )
        statement = ad_manager.StatementBuilder()
        statement.Where("id > 0")
        statement.OrderBy("id", ascending=False)
        statement.Limit(limit)

        page = creative_service.getCreativesByStatement(statement.ToStatement())
        results = getattr(page, "results", None) or []

        return [
            {
                "id": _attr(c, "id"),
                "name": (str(_attr(c, "name", "")) or str(_attr(c, "displayName", "")))[:40],
                "advertiserId": _attr(c, "advertiserId"),
            }
            for c in results
        ]

    def _get_report_credentials_path(self):
        """Resolve path to service account JSON (same logic as Node.js getClientOptions)."""
        path = self.raw_config["ad_manager"].get("path_to_private_key_file")
        if not path:
            return None
        if os.path.isabs(path):
            return path if os.path.exists(path) else None
        # Try cwd first (like Node path.resolve(process.cwd(), path))
        resolved = os.path.join(os.getcwd(), path)
        if os.path.exists(resolved):
            return resolved
        # Fallback: config dir (~/.gam-cli)
        alt = os.path.join(os.path.dirname(CONFIG_FILE), os.path.basename(path))
        return alt if os.path.exists(alt) else None

    def _get_metrics_via_report(self, dimensions, metrics_list):
        """Run report via ReportServiceClient (same API as Node.js). Returns {id_str: {impressions, clicks}}."""
        if not dimensions or not metrics_list:
            return {}
        try:
            from google.ads import admanager_v1

            creds_path = self._get_report_credentials_path()
            if creds_path:
                client = admanager_v1.ReportServiceClient.from_service_account_file(creds_path)
            else:
                client = admanager_v1.ReportServiceClient()

            parent = f"networks/{self.network_code}"
            report = admanager_v1.Report(
                display_name="gam-cli-metrics",
                report_definition=admanager_v1.ReportDefinition(
                    dimensions=dimensions,
                    metrics=metrics_list,
                    report_type="HISTORICAL",
                    date_range={"relative": "LAST_90_DAYS"},
                ),
                visibility=admanager_v1.Report.Visibility.HIDDEN,
            )
            created = client.create_report(parent=parent, report=report)
            operation = client.run_report(name=created.name)
            response = operation.result()
            result_name = response.report_result
            if not result_name:
                return {}
            metrics_map = {}
            for response in client.fetch_report_result_rows(name=result_name):
                for row in getattr(response, "rows", []) or []:
                    dims = getattr(row, "dimension_values", None) or []
                    if not dims:
                        continue
                    d0 = dims[0]
                    id_val = getattr(d0, "int_value", None) or getattr(d0, "string_value", None)
                    if id_val is None:
                        continue
                    id_str = str(id_val)
                    vals = []
                    mvg = getattr(row, "metric_value_groups", None) or []
                    if mvg:
                        pv = getattr(mvg[0], "primary_values", None) or []
                        vals = list(pv) if pv else []
                    impressions = int(getattr(vals[0], "int_value", None) or getattr(vals[0], "string_value", None) or 0) if len(vals) > 0 else 0
                    clicks = int(getattr(vals[1], "int_value", None) or getattr(vals[1], "string_value", None) or 0) if len(vals) > 1 else 0
                    if id_str not in metrics_map:
                        metrics_map[id_str] = {"impressions": 0, "clicks": 0}
                    metrics_map[id_str]["impressions"] += impressions
                    metrics_map[id_str]["clicks"] += clicks
            return metrics_map
        except Exception as e:
            if os.environ.get("GAM_DEBUG"):
                print(f"Report error: {e}", file=sys.stderr)
            return {}

    def _get_order_metrics(self, order_ids):
        """Get impressions and clicks per order (LAST_90_DAYS) via ReportServiceClient."""
        if not order_ids:
            return {}
        metrics = self._get_metrics_via_report(
            ["ORDER_ID"], ["AD_SERVER_IMPRESSIONS", "AD_SERVER_CLICKS"]
        )
        return {str(oid): metrics.get(str(oid), {"impressions": 0, "clicks": 0}) for oid in order_ids}

    def _get_line_item_metrics(self, line_item_ids):
        """Get impressions and clicks per line item (LAST_90_DAYS) via ReportServiceClient."""
        if not line_item_ids:
            return {}
        metrics = self._get_metrics_via_report(
            ["LINE_ITEM_ID"], ["AD_SERVER_IMPRESSIONS", "AD_SERVER_CLICKS"]
        )
        return {str(lid): metrics.get(str(lid), {"impressions": 0, "clicks": 0}) for lid in line_item_ids}

    def get_inventory_forecast(self, start_date, end_date, sizes=None):
        forecast_service = self.client.GetService(
            "ForecastService", version="v202511"
        )

        if not sizes:
            creative_placeholders = [
                {"size": {"width": 300, "height": 250, "isAspectRatio": False}}
            ]
        else:
            creative_placeholders = [{"size": s} for s in sizes]

        start_dt = (
            start_date
            if hasattr(start_date, "year")
            else datetime.datetime.strptime(str(start_date), "%Y-%m-%d").date()
        )
        end_dt = (
            end_date
            if hasattr(end_date, "year")
            else datetime.datetime.strptime(str(end_date), "%Y-%m-%d").date()
        )

        prospective_line_item = {
            "lineItem": {
                "targeting": {
                    "inventoryTargeting": {
                        "targetedAdUnits": [
                            {
                                "adUnitId": self._get_root_ad_unit_id(),
                                "includeDescendants": True,
                            }
                        ]
                    }
                },
                "startDateTime": self._py_date_to_gam(start_dt, 0),
                "endDateTime": self._py_date_to_gam(end_dt, 23),
                "lineItemType": "STANDARD",
                "costType": "CPM",
                "creativePlaceholders": creative_placeholders,
                "primaryGoal": {
                    "goalType": "LIFETIME",
                    "unitType": "IMPRESSIONS",
                    "units": 1000000,
                },
            }
        }

        forecast_options = {
            "includeContendingLineItems": True,
            "includeTargetingCriteriaBreakdown": True,
        }

        try:
            forecast = forecast_service.getAvailabilityForecast(
                prospective_line_item, forecast_options
            )
            matched = int(forecast["matchedUnits"])
            available = int(forecast["availableUnits"])
            return {
                "matched": matched,
                "available": available,
                "reserved": matched - available,
            }
        except Exception as e:
            return {"error": str(e)}

    def get_inventory(self, preset=None, start_date=None, end_date=None):
        """Get inventory forecast, optionally by preset. Returns rows for display."""
        today = datetime.date.today()
        start = start_date or today
        end = end_date or (today + datetime.timedelta(days=30))
        start_str = str(start)
        end_str = str(end)

        presets_to_use = (
            [preset] if preset and preset in INVENTORY_PRESETS
            else list(INVENTORY_PRESETS.keys())
        )

        rows = []
        for key in presets_to_use:
            p = INVENTORY_PRESETS[key]
            sizes = p.get("sizes")
            res = self.get_inventory_forecast(start, end, sizes)
            if "error" in res:
                rows.append({
                    "preset": key,
                    "label": p["label"],
                    "sizes": ", ".join(
                        f"{s['width']}x{s['height']}"
                        for s in (sizes or [{"width": 300, "height": 250}])
                    ) if sizes else "All",
                    "available": "-",
                    "forecasted": "-",
                    "reserved": "-",
                    "str": "-",
                })
            else:
                matched = res["matched"]
                available = res["available"]
                reserved = res["reserved"]
                str_pct = f"{(reserved / matched * 100):.1f}%" if matched else "-"
                rows.append({
                    "preset": key,
                    "label": p["label"],
                    "sizes": ", ".join(
                        f"{s['width']}x{s['height']}"
                        for s in (sizes or [{"width": 300, "height": 250}])
                    ) if sizes else "All",
                    "available": f"{available:,}",
                    "forecasted": f"{matched:,}",
                    "reserved": f"{reserved:,}",
                    "str": str_pct,
                })

        return {
            "rows": rows,
            "startStr": start_str,
            "endStr": end_str,
            "mode": "forecast",
            "error": None,
        }

    def _get_root_ad_unit_id(self):
        network_service = self.client.GetService(
            "NetworkService", version="v202511"
        )
        return network_service.getCurrentNetwork()["effectiveRootAdUnitId"]

    def _py_date_to_gam(self, dt, hour):
        if hasattr(dt, "year"):
            return {
                "date": {"year": dt.year, "month": dt.month, "day": dt.day},
                "hour": hour,
                "minute": 0,
                "second": 0,
                "timeZoneId": "America/New_York",
            }
        parts = str(dt)[:10].split("-")
        return {
            "date": {
                "year": int(parts[0]),
                "month": int(parts[1]),
                "day": int(parts[2]),
            },
            "hour": hour,
            "minute": 0,
            "second": 0,
            "timeZoneId": "America/New_York",
        }


# --- CLI Implementation ---
def format_table(headers, rows):
    if not rows:
        return
    widths = [
        max(len(str(h)), max(len(str(r[i])) for r in rows))
        for i, h in enumerate(headers)
    ]
    fmt = "  ".join(f"{{:<{w}}}" for w in widths)
    print(fmt.format(*headers))
    print("-" * (sum(widths) + len(widths) * 2))
    for r in rows:
        print(fmt.format(*[str(x)[:50] for x in r]))


def print_help():
    print(__doc__.strip())


def init_gam(config_path):
    """Initialize config by copying to ~/.gam-cli/config.yaml."""
    try:
        resolved = (
            os.path.abspath(config_path)
            if not os.path.isabs(config_path)
            else config_path
        )
        resolved = os.path.normpath(resolved)
        if not os.path.exists(resolved):
            raise FileNotFoundError(f"Config file not found: {resolved}")

        with open(resolved, "r") as f:
            config = yaml.safe_load(f)

        if not config or "ad_manager" not in config:
            raise ValueError('Invalid config: missing "ad_manager" section')
        if not config["ad_manager"].get("network_code"):
            raise ValueError('Invalid config: missing "ad_manager.network_code"')

        ensure_config_dir()
        shutil.copy(resolved, CONFIG_FILE)
        print("Configuration saved!")
        print(f"Network Code: {config['ad_manager']['network_code']}")
    except Exception as e:
        exit_with_error(e, "init")


def main():
    args = sys.argv[1:]
    if not args:
        print_help()
        sys.exit(0)

    cmd = args[0]
    opts = parse_opts(args)

    # Handle init (doesn't need GAMService)
    if cmd == "init":
        if len(args) < 2:
            print("Error: Config path required")
            print("Usage: gam init <path-to-gam.yaml>")
            sys.exit(1)
        init_gam(args[1])
        return

    # Default dates for inventory
    today = datetime.date.today()
    start_dt = opts["start"] or (today + datetime.timedelta(days=1))
    end_dt = opts["end"] or (start_dt + datetime.timedelta(days=7))

    try:
        gam = GAMService()

        if cmd == "user":
            user = gam.get_user()
            if opts["json"]:
                print(json.dumps(user, indent=2))
            else:
                print("\n=== GAM Connection Info ===\n")
                print(f"User: {user['displayName']}")
                print(f"Email: {user['email']}")
                print(f"User ID: {user['id']}")
                print(f"Role: {user['roleName']}")

        elif cmd == "orders":
            orders = gam.get_orders(opts["limit"], opts["status"])
            if opts["json"]:
                print(json.dumps(orders, indent=2))
            else:
                print(f"\n=== Orders (showing {len(orders)}) ===\n")
                if not orders:
                    print("No orders found.")
                else:
                    format_table(
                        ["ID", "Name", "Status", "Start", "End", "Impressions", "Clicks", "Currency", "Advertiser"],
                        [
                            [
                                o["id"],
                                o["name"],
                                o["status"],
                                o["startDate"],
                                o["endDate"],
                                f"{o.get('impressions', 0):,}",
                                f"{o.get('clicks', 0):,}",
                                o["currency"],
                                o["advertiserId"],
                            ]
                            for o in orders
                        ],
                    )

        elif cmd == "line-items":
            order_id = opts["order_id"]
            if order_id and order_id.isdigit():
                order_id = int(order_id)
            line_items = gam.get_line_items(order_id, opts["limit"])
            if opts["json"]:
                print(json.dumps(line_items, indent=2))
            else:
                print(f"\n=== Line Items (showing {len(line_items)}) ===\n")
                if not line_items:
                    print("No line items found.")
                else:
                    format_table(
                        ["ID", "Name", "Order ID", "Status", "Type", "Start", "End", "Impressions", "Clicks", "CTR", "Progress"],
                        [
                            [
                                li["id"],
                                li["name"],
                                li["orderId"],
                                li["status"],
                                li["lineItemType"],
                                li["startDate"],
                                li["endDate"],
                                f"{li.get('impressions', 0):,}",
                                f"{li.get('clicks', 0):,}",
                                li.get("ctr", "-"),
                                li.get("progress", "-"),
                            ]
                            for li in line_items
                        ],
                    )

        elif cmd == "inventory":
            inv = gam.get_inventory(
                opts["preset"], opts["start"] or start_dt, opts["end"] or end_dt
            )
            if opts["json"]:
                print(json.dumps(inv, indent=2))
            else:
                range_str = f"{inv['startStr']} to {inv['endStr']}"
                print(f"\n=== Inventory Forecast ({range_str}) ===\n")
                if inv["rows"]:
                    format_table(
                        ["Preset", "Sizes", "Available", "Forecasted", "Reserved", "STR%"],
                        [
                            [
                                r["preset"],
                                r["sizes"],
                                r["available"],
                                r["forecasted"],
                                r["reserved"],
                                r["str"],
                            ]
                            for r in inv["rows"]
                        ],
                    )
                else:
                    print("No inventory data.")

        elif cmd == "networks":
            networks = gam.get_networks()
            if opts["json"]:
                print(json.dumps(networks, indent=2))
            else:
                print("\n=== Available Networks ===\n")
                for n in networks:
                    print(f"Network Code: {n['networkCode']}")
                    print(f"Display Name: {n['displayName']}")
                    print(f"Property Code: {n['propertyCode']}")
                    print()

        elif cmd == "creatives":
            creatives = gam.get_creatives(opts["limit"])
            if opts["json"]:
                print(json.dumps(creatives, indent=2))
            else:
                print(f"\n=== Creatives (showing {len(creatives)}) ===\n")
                if creatives:
                    format_table(
                        ["ID", "Name", "Advertiser ID"],
                        [[c["id"], c["name"], c["advertiserId"]] for c in creatives],
                    )
                else:
                    print("No creatives found.")

        else:
            print(f"Unknown command: {cmd}")
            print('Run "gam" without args to see available commands')
            sys.exit(1)

    except Exception as e:
        exit_with_error(e, f"gam {cmd}")


if __name__ == "__main__":
    main()
