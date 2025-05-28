#!/usr/bin/env python3
"""
quota_utils.py

Provides utilities to query OpenAI usage (billing) via the HTTP Dashboard API
and summarize quota consumption and subscription details.
"""

from datetime import date, timedelta
import requests

API_BASE = "https://api.openai.com/v1/dashboard"

def summarize_usage(api_key: str, days: int = 30):
    """
    Fetch token usage over the past `days` days using the OpenAI Billing Usage API.

    Returns:
      (start_date_iso, end_date_iso, usage_summary, subscription_info)

    where
      usage_summary = { date: total_tokens, ... }
      subscription_info = { ... }  # raw JSON of your plan/quota
    """
    end_date = date.today()
    start_date = end_date - timedelta(days=days)

    headers = {"Authorization": f"Bearer {api_key}"}

    # 1) Billing Usage
    usage_url = f"{API_BASE}/billing/usage"
    usage_params = {
        "start_date": start_date.isoformat(),
        "end_date":   end_date.isoformat(),
    }
    uresp = requests.get(usage_url, headers=headers, params=usage_params)
    uresp.raise_for_status()
    udata = uresp.json().get("daily_costs", [])

    # Summarize by date
    usage_summary: dict[str, float] = {}
    for entry in udata:
        d = entry.get("date")
        cost = entry.get("cost", 0.0)      # cost in USD
        usage_summary[d] = usage_summary.get(d, 0.0) + cost

    # 2) Subscription / Plan
    sub_url = f"{API_BASE}/billing/subscription"
    sresp = requests.get(sub_url, headers=headers)
    sresp.raise_for_status()
    sub_info = sresp.json()

    return (
        start_date.isoformat(),
        end_date.isoformat(),
        usage_summary,
        sub_info
    )
