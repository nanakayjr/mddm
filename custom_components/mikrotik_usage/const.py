"""Constants for Mikrotik Data Usage."""

DOMAIN = "mikrotik_usage"

CONF_DEVICES = "devices"
CONF_PERIODS = "periods"
CONF_SWAP = "swap_direction"
CONF_HA_HOST = "ha_host"
CONF_ESTIMATE = "estimate_services"
CONF_PREFER_RATE = "prefer_rate"

PERIODS = ("day", "month", "year")
PERIOD_LABEL = {"day": "Today", "month": "This month", "year": "This year"}

SCAN_SECONDS = 30
ESTIMATE_REFRESH_S = 600

# Integration platforms we prefer to surface during onboarding.
MIKROTIK_PLATFORMS = {"mikrotik_extended", "mikrotik_router", "mikrotik"}

PANEL_URL = "mikrotik-usage"
STATIC_URL = "/mikrotik_usage_static/mikrotik-usage-panel.js"
