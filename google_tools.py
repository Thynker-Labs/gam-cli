#!/usr/bin/env python3
"""
Unified Google Analytics 4 (GA4) and Google Ad Manager (GAM) CLI Tool

Supports:
- GA4 analytics data queries
- GA4 OAuth token setup
- Google Ad Manager operations

Authentication:
  GA4: Service account (GOOGLE_APPLICATION_CREDENTIALS) or OAuth (GOOGLE_CLIENT_ID/SECRET/REFRESH_TOKEN)
  GAM: Service account via YAML config file

Install dependencies:
  pip install google-analytics-data google-auth-oauthlib googleads requests tabulate pyyaml

Examples:
  # GA4 Queries
  python google_tools.py ga4 --property 268092156 --metrics screenPageViews --dimensions pagePath --limit 10
  python google_tools.py ga4 -p 268092156 -m sessions,screenPageViews -d pagePath --filter "pagePath=~/news/" --json

  # GA4 OAuth Setup
  python google_tools.py ga4-auth url --client-id YOUR_CLIENT_ID
  python google_tools.py ga4-auth exchange --client-id YOUR_CLIENT_ID --client-secret YOUR_SECRET --code AUTH_CODE

  # Google Ad Manager
  python google_tools.py gam --config gam.yaml user
  python google_tools.py gam --config gam.yaml orders --limit 10
  python google_tools.py gam --config gam.yaml line-items --order-id 12345
  python google_tools.py gam --config gam.yaml inventory --start 2026-02-24 --end 2026-03-10
"""

import argparse
import json
import os
import sys
import urllib.parse
from datetime import date, datetime, timedelta
from typing import List, Optional

# Lazy imports to avoid requiring all dependencies for each subcommand
def require_ga4():
    """Import GA4 dependencies."""
    try:
        from google.analytics.data_v1beta import BetaAnalyticsDataClient
        from google.analytics.data_v1beta.types import (
            DateRange,
            Dimension,
            Metric,
            RunReportRequest,
            FilterExpression,
            Filter,
            OrderBy,
        )
        from google.oauth2.credentials import Credentials
        return {
            "BetaAnalyticsDataClient": BetaAnalyticsDataClient,
            "DateRange": DateRange,
            "Dimension": Dimension,
            "Metric": Metric,
            "RunReportRequest": RunReportRequest,
            "FilterExpression": FilterExpression,
            "Filter": Filter,
            "OrderBy": OrderBy,
            "Credentials": Credentials,
        }
    except ImportError:
        print("Missing GA4 dependencies. Install with:")
        print("  pip install google-analytics-data google-auth-oauthlib")
        sys.exit(1)


def require_gam():
    """Import GAM dependencies."""
    try:
        from googleads import ad_manager
        return {"ad_manager": ad_manager}
    except ImportError:
        print("Missing GAM dependencies. Install with:")
        print("  pip install googleads")
        sys.exit(1)


def require_tabulate():
    """Import tabulate for pretty tables."""
    try:
        from tabulate import tabulate
        return tabulate
    except ImportError:
        return None


# =============================================================================
# GA4 Authentication
# =============================================================================

def get_ga4_credentials(service_account_path: Optional[str] = None):
    """Get GA4 credentials from service account or OAuth env vars.
    
    Priority:
    1. Explicit service_account_path argument
    2. GOOGLE_APPLICATION_CREDENTIALS env var
    3. OAuth credentials from env vars
    """
    # 1) Explicit path or env var for service account
    sa_path = service_account_path or os.environ.get("GOOGLE_APPLICATION_CREDENTIALS")
    if sa_path:
        try:
            from google.oauth2 import service_account
            scopes = ["https://www.googleapis.com/auth/analytics.readonly"]
            return service_account.Credentials.from_service_account_file(sa_path, scopes=scopes)
        except Exception as e:
            print(f"Error loading service account credentials: {e}")
            sys.exit(1)

    # 2) OAuth user credentials
    client_id = os.environ.get("GOOGLE_CLIENT_ID")
    client_secret = os.environ.get("GOOGLE_CLIENT_SECRET")
    refresh_token = os.environ.get("GOOGLE_REFRESH_TOKEN")

    if not all([client_id, client_secret, refresh_token]):
        print("Error: Missing authentication credentials.")
        print("\nProvide either:")
        print("  --service-account /path/to/service-account.json")
        print("  or GOOGLE_APPLICATION_CREDENTIALS=/path/to/service-account.json")
        print("  or set GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET, GOOGLE_REFRESH_TOKEN")
        sys.exit(1)

    ga4 = require_ga4()
    return ga4["Credentials"](
        token=None,
        refresh_token=refresh_token,
        client_id=client_id,
        client_secret=client_secret,
        token_uri="https://oauth2.googleapis.com/token",
    )


# =============================================================================
# GA4 Query Functions
# =============================================================================

def parse_ga4_filter(filter_str: str, Filter, FilterExpression):
    """Parse filter string into FilterExpression.
    
    Supported formats:
    - dimension=value     (contains match, case insensitive)
    - dimension==value    (exact match)
    - dimension=~regex    (regex match)
    - dimension!=value    (not equals)
    """
    if not filter_str:
        return None

    # Regex match: =~
    if "=~" in filter_str:
        dim, pattern = filter_str.split("=~", 1)
        return FilterExpression(
            filter=Filter(
                field_name=dim.strip(),
                string_filter=Filter.StringFilter(
                    match_type=Filter.StringFilter.MatchType.PARTIAL_REGEXP,
                    value=pattern.strip(),
                ),
            )
        )
    
    # Exact match: ==
    elif "==" in filter_str:
        dim, value = filter_str.split("==", 1)
        return FilterExpression(
            filter=Filter(
                field_name=dim.strip(),
                string_filter=Filter.StringFilter(
                    match_type=Filter.StringFilter.MatchType.EXACT,
                    value=value.strip(),
                ),
            )
        )
    
    # Not equals: !=
    elif "!=" in filter_str:
        dim, value = filter_str.split("!=", 1)
        # Note: FilterExpression doesn't have not_expression at top level
        # Use in_list_filter with negation
        return FilterExpression(
            not_expression=FilterExpression(
                filter=Filter(
                    field_name=dim.strip(),
                    string_filter=Filter.StringFilter(
                        match_type=Filter.StringFilter.MatchType.EXACT,
                        value=value.strip(),
                    ),
                )
            )
        )
    
    # Contains match: =
    elif "=" in filter_str:
        dim, value = filter_str.split("=", 1)
        return FilterExpression(
            filter=Filter(
                field_name=dim.strip(),
                string_filter=Filter.StringFilter(
                    match_type=Filter.StringFilter.MatchType.CONTAINS,
                    value=value.strip(),
                    case_sensitive=False,
                ),
            )
        )
    
    return None


def run_ga4_report(args):
    """Run a GA4 analytics report."""
    ga4 = require_ga4()
    tabulate = require_tabulate()
    
    # Get property ID
    property_id = args.property or os.environ.get("GA4_PROPERTY_ID")
    if not property_id:
        print("Error: GA4 Property ID required.")
        print("  Use --property/-p or set GA4_PROPERTY_ID env var.")
        print("\nFind your Property ID in GA4 Admin → Property Settings")
        sys.exit(1)
    
    # Get credentials
    credentials = get_ga4_credentials(args.service_account)
    client = ga4["BetaAnalyticsDataClient"](credentials=credentials)
    
    # Parse metrics and dimensions
    metrics = [m.strip() for m in args.metrics.split(",") if m.strip()]
    dimensions = [d.strip() for d in args.dimensions.split(",") if d.strip()]
    
    # Parse dates
    end_date = args.end or "yesterday"
    start_date = args.start or "30daysAgo"
    
    # Build request
    request_kwargs = {
        "property": f"properties/{property_id}",
        "dimensions": [ga4["Dimension"](name=d) for d in dimensions],
        "metrics": [ga4["Metric"](name=m) for m in metrics],
        "date_ranges": [ga4["DateRange"](start_date=start_date, end_date=end_date)],
        "limit": args.limit,
    }
    
    # Add filter if provided
    if args.filter:
        filter_expr = parse_ga4_filter(args.filter, ga4["Filter"], ga4["FilterExpression"])
        if filter_expr:
            request_kwargs["dimension_filter"] = filter_expr
    
    # Add ordering if provided
    if args.order_by:
        try:
            ob_metric, ob_dir = args.order_by.split(":", 1)
            request_kwargs["order_bys"] = [
                ga4["OrderBy"](
                    metric=ga4["OrderBy"].MetricOrderBy(metric_name=ob_metric.strip()),
                    desc=(ob_dir.strip().lower() == "desc"),
                )
            ]
        except ValueError:
            print("Error: --order-by must be formatted as 'metric:desc' or 'metric:asc'")
            sys.exit(1)
    
    request = ga4["RunReportRequest"](**request_kwargs)
    response = client.run_report(request)
    
    # Format output
    if args.json:
        results = []
        for row in response.rows:
            item = {}
            for i, dv in enumerate(row.dimension_values):
                item[dimensions[i]] = dv.value
            for i, mv in enumerate(row.metric_values):
                item[metrics[i]] = mv.value
            results.append(item)
        output = {
            "property": property_id,
            "date_range": {"start": start_date, "end": end_date},
            "dimensions": dimensions,
            "metrics": metrics,
            "row_count": response.row_count,
            "rows": results,
        }
        print(json.dumps(output, indent=2))
    
    elif args.csv:
        headers = dimensions + metrics
        print(",".join(headers))
        for row in response.rows:
            values = [dv.value for dv in row.dimension_values] + [mv.value for mv in row.metric_values]
            escaped = [f'"{v}"' if "," in v else v for v in values]
            print(",".join(escaped))
    
    else:
        # Table output
        headers = dimensions + metrics
        rows = []
        for row in response.rows:
            rows.append(
                [dv.value for dv in row.dimension_values] + 
                [mv.value for mv in row.metric_values]
            )
        
        print(f"\nGA4 Report: {start_date} to {end_date}")
        print(f"Property: {property_id}\n")
        
        if tabulate:
            print(tabulate(rows, headers=headers, tablefmt="github"))
        else:
            # Simple table fallback
            col_widths = [max(len(str(h)), 10) for h in headers]
            for row in rows:
                for i, v in enumerate(row):
                    col_widths[i] = max(col_widths[i], min(len(str(v)), 50))
            
            header_line = " | ".join(h.ljust(col_widths[i]) for i, h in enumerate(headers))
            print(header_line)
            print("-" * len(header_line))
            for row in rows:
                print(" | ".join(str(v)[:50].ljust(col_widths[i]) for i, v in enumerate(row)))
        
        print(f"\nTotal rows: {response.row_count}")


# =============================================================================
# GA4 OAuth Setup
# =============================================================================

GA4_SCOPES = ["https://www.googleapis.com/auth/analytics.readonly"]


def generate_ga4_auth_url(client_id: str, redirect_uri: str = "http://localhost:8080/") -> str:
    """Generate OAuth authorization URL."""
    params = {
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "scope": " ".join(GA4_SCOPES),
        "response_type": "code",
        "access_type": "offline",
        "prompt": "consent",
    }
    base_url = "https://accounts.google.com/o/oauth2/auth"
    return f"{base_url}?{urllib.parse.urlencode(params)}"


def exchange_ga4_code(client_id: str, client_secret: str, code: str, redirect_uri: str = "http://localhost:8080/"):
    """Exchange authorization code for tokens."""
    try:
        import requests
    except ImportError:
        print("Missing requests library. Install with: pip install requests")
        sys.exit(1)
    
    response = requests.post(
        "https://oauth2.googleapis.com/token",
        data={
            "client_id": client_id,
            "client_secret": client_secret,
            "code": code,
            "grant_type": "authorization_code",
            "redirect_uri": redirect_uri,
        },
    )
    
    if response.status_code != 200:
        print(f"Error exchanging code: {response.text}")
        sys.exit(1)
    
    return response.json()


def run_ga4_auth(args):
    """Handle GA4 OAuth setup commands."""
    if args.auth_command == "url":
        url = generate_ga4_auth_url(args.client_id, args.redirect_uri)
        print("\n=== GA4 OAuth Authorization ===\n")
        print("1. Open this URL in your browser:")
        print(f"\n   {url}\n")
        print("2. Sign in and authorize access to Analytics")
        print("3. Copy the 'code' parameter from the redirect URL")
        print("4. Run:")
        print(f"   python google_tools.py ga4-auth exchange --client-id {args.client_id} --client-secret YOUR_SECRET --code AUTH_CODE")
    
    elif args.auth_command == "exchange":
        print("Exchanging authorization code for tokens...")
        tokens = exchange_ga4_code(
            args.client_id,
            args.client_secret,
            args.code,
            args.redirect_uri,
        )
        print("\n=== OAuth Tokens ===\n")
        access_token = tokens.get('access_token', 'N/A')
        print(f"Access Token: {access_token[:50]}..." if len(access_token) > 50 else f"Access Token: {access_token}")
        print(f"Refresh Token: {tokens.get('refresh_token', 'N/A')}")
        print(f"Expires In: {tokens.get('expires_in', 'N/A')} seconds")
        print("\n=== Environment Variables ===\n")
        print("Add these to your shell or .env file:\n")
        print(f"export GOOGLE_CLIENT_ID='{args.client_id}'")
        print(f"export GOOGLE_CLIENT_SECRET='{args.client_secret}'")
        print(f"export GOOGLE_REFRESH_TOKEN='{tokens.get('refresh_token')}'")


# =============================================================================
# Google Ad Manager Functions
# =============================================================================

def run_gam(args):
    """Handle Google Ad Manager commands."""
    gam = require_gam()
    ad_manager = gam["ad_manager"]
    tabulate = require_tabulate()
    
    # Load client from YAML config
    config_path = args.config
    if not os.path.exists(config_path):
        print(f"Error: GAM config file not found: {config_path}")
        print("\nCreate a gam.yaml file with format:")
        print("""
ad_manager:
  application_name: "Your App Name"
  network_code: "YOUR_NETWORK_CODE"
  path_to_private_key_file: "/path/to/service-account.json"
""")
        sys.exit(1)
    
    try:
        client = ad_manager.AdManagerClient.LoadFromStorage(config_path)
    except Exception as e:
        print(f"Error loading GAM config: {e}")
        sys.exit(1)
    
    if args.gam_command == "user":
        # Show current user info
        user_service = client.GetService("UserService")
        me = user_service.getCurrentUser()
        print("\n=== GAM Connection Info ===\n")
        print(f"User: {getattr(me, 'displayName', 'N/A')}")
        print(f"Email: {getattr(me, 'email', 'N/A')}")
        print(f"User ID: {getattr(me, 'id', 'N/A')}")
        print(f"Role: {getattr(me, 'roleName', 'N/A')}")
    
    elif args.gam_command == "orders":
        # List orders
        order_service = client.GetService("OrderService")
        statement = ad_manager.StatementBuilder()
        statement.Where("id > 0")
        statement.OrderBy("id", ascending=False)
        statement.Limit(args.limit)
        
        if args.status:
            statement.Where(f"status = '{args.status}'")
        
        page = order_service.getOrdersByStatement(statement.ToStatement())
        results = getattr(page, 'results', None) or []
        
        print(f"\n=== Orders (showing {len(results)}) ===\n")
        
        if args.json:
            orders_data = []
            for o in results:
                orders_data.append({
                    "id": getattr(o, 'id', None),
                    "name": getattr(o, 'name', None),
                    "status": getattr(o, 'status', None),
                    "advertiser_id": getattr(o, 'advertiserId', None),
                    "start_date": str(getattr(o, 'startDateTime', None)),
                    "end_date": str(getattr(o, 'endDateTime', None)),
                })
            print(json.dumps(orders_data, indent=2))
        else:
            rows = []
            for o in results:
                rows.append([
                    getattr(o, 'id', 'N/A'),
                    getattr(o, 'name', 'N/A')[:40],
                    getattr(o, 'status', 'N/A'),
                ])
            
            headers = ["ID", "Name", "Status"]
            if tabulate:
                print(tabulate(rows, headers=headers, tablefmt="github"))
            else:
                print(f"{'ID':<15} {'Name':<42} {'Status':<15}")
                print("-" * 75)
                for row in rows:
                    print(f"{row[0]:<15} {row[1]:<42} {row[2]:<15}")
    
    elif args.gam_command == "line-items":
        # List line items
        line_item_service = client.GetService("LineItemService")
        statement = ad_manager.StatementBuilder()
        
        if args.order_id:
            statement.Where(f"orderId = {args.order_id}")
        else:
            statement.Where("id > 0")
        
        statement.OrderBy("id", ascending=False)
        statement.Limit(args.limit)
        
        page = line_item_service.getLineItemsByStatement(statement.ToStatement())
        results = getattr(page, 'results', None) or []
        
        print(f"\n=== Line Items (showing {len(results)}) ===\n")
        
        if args.json:
            items_data = []
            for li in results:
                items_data.append({
                    "id": getattr(li, 'id', None),
                    "name": getattr(li, 'name', None),
                    "order_id": getattr(li, 'orderId', None),
                    "status": getattr(li, 'status', None),
                    "line_item_type": getattr(li, 'lineItemType', None),
                })
            print(json.dumps(items_data, indent=2))
        else:
            rows = []
            for li in results:
                rows.append([
                    getattr(li, 'id', 'N/A'),
                    getattr(li, 'name', 'N/A')[:35],
                    getattr(li, 'orderId', 'N/A'),
                    getattr(li, 'status', 'N/A'),
                ])
            
            headers = ["ID", "Name", "Order ID", "Status"]
            if tabulate:
                print(tabulate(rows, headers=headers, tablefmt="github"))
            else:
                print(f"{'ID':<15} {'Name':<37} {'Order ID':<15} {'Status':<15}")
                print("-" * 85)
                for row in rows:
                    print(f"{row[0]:<15} {row[1]:<37} {row[2]:<15} {row[3]:<15}")
    
    elif args.gam_command == "networks":
        # List available networks
        network_service = client.GetService("NetworkService")
        networks = network_service.getAllNetworks()
        
        print("\n=== Available Networks ===\n")
        
        if args.json:
            networks_data = []
            for n in networks:
                networks_data.append({
                    "network_code": getattr(n, 'networkCode', None),
                    "display_name": getattr(n, 'displayName', None),
                    "property_code": getattr(n, 'propertyCode', None),
                })
            print(json.dumps(networks_data, indent=2))
        else:
            for n in networks:
                print(f"Network Code: {getattr(n, 'networkCode', 'N/A')}")
                print(f"Display Name: {getattr(n, 'displayName', 'N/A')}")
                print(f"Property Code: {getattr(n, 'propertyCode', 'N/A')}")
                print()
    
    elif args.gam_command == "creatives":
        # List creatives
        creative_service = client.GetService("CreativeService")
        statement = ad_manager.StatementBuilder()
        statement.Where("id > 0")
        statement.OrderBy("id", ascending=False)
        statement.Limit(args.limit)
        
        page = creative_service.getCreativesByStatement(statement.ToStatement())
        results = getattr(page, 'results', None) or []
        
        print(f"\n=== Creatives (showing {len(results)}) ===\n")
        
        if args.json:
            creatives_data = []
            for c in results:
                creatives_data.append({
                    "id": getattr(c, 'id', None),
                    "name": getattr(c, 'name', None),
                    "advertiser_id": getattr(c, 'advertiserId', None),
                })
            print(json.dumps(creatives_data, indent=2))
        else:
            rows = []
            for c in results:
                rows.append([
                    getattr(c, 'id', 'N/A'),
                    getattr(c, 'name', 'N/A')[:40],
                    getattr(c, 'advertiserId', 'N/A'),
                ])
            
            headers = ["ID", "Name", "Advertiser ID"]
            if tabulate:
                print(tabulate(rows, headers=headers, tablefmt="github"))
            else:
                print(f"{'ID':<15} {'Name':<42} {'Advertiser ID':<15}")
                print("-" * 75)
                for row in rows:
                    print(f"{row[0]:<15} {row[1]:<42} {row[2]:<15}")

    elif args.gam_command == "inventory":
        # Future forecast via ForecastService.getTrafficData (Ad Manager 360 only)
        today = date.today()
        start_arg = getattr(args, "start", None)
        end_arg = getattr(args, "end", None)

        def parse_date(s):
            if not s:
                return None
            s = s.strip()
            if len(s) == 8 and s.isdigit():  # DDMMYYYY
                return date(int(s[4:8]), int(s[2:4]), int(s[0:2]))
            if len(s) >= 10 and s[4] == "-":  # YYYY-MM-DD
                parts = s[:10].split("-")
                if len(parts) == 3:
                    return date(int(parts[0]), int(parts[1]), int(parts[2]))
            return None

        start_date = parse_date(start_arg) if start_arg else today - timedelta(days=7)
        end_date = parse_date(end_arg) if end_arg else today + timedelta(days=30)

        try:
            forecast_service = client.GetService("ForecastService", version="v202511")
            network_service = client.GetService("NetworkService", version="v202511")
            root_ad_unit_id = network_service.getCurrentNetwork()["effectiveRootAdUnitId"]

            targeting = {
                "inventoryTargeting": {
                    "targetedAdUnits": [
                        {"includeDescendants": True, "adUnitId": root_ad_unit_id}
                    ]
                }
            }

            traffic_data = forecast_service.getTrafficData({
                "targeting": targeting,
                "requestedDateRange": {
                    "startDate": start_date,
                    "endDate": end_date,
                },
            })

            fts = traffic_data.get("forecastedTimeSeries")
            if not fts or not fts.get("values"):
                print("\n=== Inventory Forecast ===\n")
                print("No forecasted data returned.")
                sys.exit(0)

            total = sum(int(v) for v in fts["values"])
            if args.json:
                print(json.dumps({"forecasted": total, "start": str(start_date), "end": str(end_date)}))
            else:
                print("\n=== Inventory Forecast (getTrafficData) ===\n")
                print(f"Date range: {start_date} to {end_date}")
                print(f"Forecasted impressions: {total:,}")
        except Exception as e:
            err_str = str(e)
            if "UNSUPPORTED_OPERATION" in err_str or "CommonError" in err_str:
                print("\ngetTrafficData requires Ad Manager 360. This network may not have access.")
            else:
                print(f"\nError: {e}")
            sys.exit(1)


# =============================================================================
# Main CLI
# =============================================================================

def main():
    parser = argparse.ArgumentParser(
        prog="google_tools",
        description="Unified CLI for Google Analytics 4 and Google Ad Manager",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # GA4 Analytics Query
  %(prog)s ga4 --property 268092156 --metrics screenPageViews,sessions --dimensions pagePath
  %(prog)s ga4 -p 268092156 --filter "pagePath=~/news/" --json

  # GA4 OAuth Setup
  %(prog)s ga4-auth url --client-id YOUR_CLIENT_ID
  %(prog)s ga4-auth exchange --client-id ID --client-secret SECRET --code AUTH_CODE

  # Google Ad Manager
  %(prog)s gam --config gam.yaml user
  %(prog)s gam --config gam.yaml orders --limit 20
  %(prog)s gam --config gam.yaml line-items --order-id 12345
""",
    )
    
    subparsers = parser.add_subparsers(dest="command", help="Available commands")
    
    # -------------------------------------------------------------------------
    # GA4 Query Subcommand
    # -------------------------------------------------------------------------
    ga4_parser = subparsers.add_parser("ga4", help="Query GA4 Analytics data")
    ga4_parser.add_argument("--property", "-p", help="GA4 Property ID (or set GA4_PROPERTY_ID env var)")
    ga4_parser.add_argument("--service-account", "-sa", help="Path to service account JSON file")
    ga4_parser.add_argument("--metrics", "-m", default="screenPageViews",
                           help="Comma-separated metrics (default: screenPageViews)")
    ga4_parser.add_argument("--dimensions", "-d", default="pagePath",
                           help="Comma-separated dimensions (default: pagePath)")
    ga4_parser.add_argument("--start", "-s", default="30daysAgo",
                           help="Start date (YYYY-MM-DD or relative like 30daysAgo)")
    ga4_parser.add_argument("--end", "-e", default="yesterday",
                           help="End date (YYYY-MM-DD or relative like yesterday)")
    ga4_parser.add_argument("--limit", "-l", type=int, default=25, help="Max rows (default: 25)")
    ga4_parser.add_argument("--filter", "-f",
                           help="Filter (e.g., 'pagePath=~/blog/', 'pagePath==exact', 'pagePath!=exclude')")
    ga4_parser.add_argument("--order-by", "-o",
                           help="Order by metric (e.g., 'screenPageViews:desc')")
    ga4_parser.add_argument("--json", action="store_true", help="Output as JSON")
    ga4_parser.add_argument("--csv", action="store_true", help="Output as CSV")
    
    # -------------------------------------------------------------------------
    # GA4 Auth Subcommand
    # -------------------------------------------------------------------------
    ga4_auth_parser = subparsers.add_parser("ga4-auth", help="GA4 OAuth setup helper")
    ga4_auth_subparsers = ga4_auth_parser.add_subparsers(dest="auth_command", help="Auth commands")
    
    # ga4-auth url
    url_parser = ga4_auth_subparsers.add_parser("url", help="Generate OAuth authorization URL")
    url_parser.add_argument("--client-id", required=True, help="OAuth Client ID")
    url_parser.add_argument("--redirect-uri", default="http://localhost:8080/", help="Redirect URI")
    
    # ga4-auth exchange
    exchange_parser = ga4_auth_subparsers.add_parser("exchange", help="Exchange code for tokens")
    exchange_parser.add_argument("--client-id", required=True, help="OAuth Client ID")
    exchange_parser.add_argument("--client-secret", required=True, help="OAuth Client Secret")
    exchange_parser.add_argument("--code", required=True, help="Authorization code from redirect")
    exchange_parser.add_argument("--redirect-uri", default="http://localhost:8080/", help="Redirect URI")
    
    # -------------------------------------------------------------------------
    # GAM Subcommand
    # -------------------------------------------------------------------------
    gam_parser = subparsers.add_parser("gam", help="Google Ad Manager operations")
    gam_parser.add_argument("--config", "-c", default="gam.yaml",
                           help="Path to GAM YAML config file (default: gam.yaml)")
    gam_parser.add_argument("--json", action="store_true", help="Output as JSON")
    
    gam_subparsers = gam_parser.add_subparsers(dest="gam_command", help="GAM commands")
    
    # gam user
    gam_subparsers.add_parser("user", help="Show current user info")
    
    # gam orders
    orders_parser = gam_subparsers.add_parser("orders", help="List orders")
    orders_parser.add_argument("--limit", "-l", type=int, default=10, help="Max orders to show")
    orders_parser.add_argument("--status", help="Filter by status (e.g., APPROVED, DRAFT)")
    
    # gam line-items
    li_parser = gam_subparsers.add_parser("line-items", help="List line items")
    li_parser.add_argument("--order-id", type=int, help="Filter by order ID")
    li_parser.add_argument("--limit", "-l", type=int, default=10, help="Max items to show")
    
    # gam networks
    gam_subparsers.add_parser("networks", help="List available networks")
    
    # gam creatives
    creatives_parser = gam_subparsers.add_parser("creatives", help="List creatives")
    creatives_parser.add_argument("--limit", "-l", type=int, default=10, help="Max creatives to show")
    
    # gam inventory (future forecast via getTrafficData - Ad Manager 360 only)
    inv_parser = gam_subparsers.add_parser("inventory", help="Future inventory forecast (getTrafficData, Ad Manager 360)")
    inv_parser.add_argument("--start", help="Start date (YYYY-MM-DD or DDMMYYYY)")
    inv_parser.add_argument("--end", help="End date (YYYY-MM-DD or DDMMYYYY)")
    
    # -------------------------------------------------------------------------
    # Parse and dispatch
    # -------------------------------------------------------------------------
    args = parser.parse_args()
    
    if not args.command:
        parser.print_help()
        sys.exit(1)
    
    if args.command == "ga4":
        run_ga4_report(args)
    elif args.command == "ga4-auth":
        if not args.auth_command:
            ga4_auth_parser.print_help()
            sys.exit(1)
        run_ga4_auth(args)
    elif args.command == "gam":
        if not args.gam_command:
            gam_parser.print_help()
            sys.exit(1)
        run_gam(args)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        sys.exit(130)
