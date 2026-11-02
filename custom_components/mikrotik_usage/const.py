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

# Add-on network profiles.  Supervisor network_rx/tx counts everything crossing the
# container's veth on the internal `hassio` bridge (172.30.32.0/23), not just internet traffic.
PROFILE_LOCAL = "local_ipc_and_ingress_only"
PROFILE_BACKUP = "wan_egress_backup"
PROFILE_TUNNEL = "wan_tunnel_proxy"
PROFILE_STANDARD = "standard_wan_capable"
ADDON_PROFILE_LABEL = {
    PROFILE_LOCAL: "Local only",
    PROFILE_BACKUP: "Backup (upload = internet)",
    PROFILE_TUNNEL: "Tunnel / proxy",
    PROFILE_STANDARD: "Internet capable",
}

# Slugs are matched without their repository prefix ("core_", "a0d7b954_", ...).
LOCAL_ADDON_NAMES = frozenset({
    "configurator", "influxdb", "mosquitto", "grafana", "ssh", "vscode", "sqlite-web",
    "chrony", "zigbee2mqtt", "tasmoadmin", "samba", "samba_backup", "terminal",
    "matter_server", "openthread_border_router", "silabs_multiprotocol", "deconz",
    "zwave_js", "rpc_shutdown", "mariadb", "postgres", "adminer", "phpmyadmin",
})
BACKUP_ADDON_NAMES = frozenset({
    "hassio_google_drive_backup", "onedrive_backup", "dropbox_sync", "hassio_onedrive_backup",
    "hassio_dropbox_sync", "google_drive_backup",
})
TUNNEL_ADDON_NAMES = frozenset({
    "cloudflared", "tailscale", "wireguard", "nginx_proxy", "nginx_proxy_manager",
    "nginxproxymanager", "ngrok", "zerotier", "openvpn_server",
})
# Ingress-only add-ons that nevertheless download from the internet: never auto-classified local.
WAN_HINT_NAMES = frozenset({
    "esphome", "node-red", "nodered", "firefox", "plex", "jellyfin", "emby", "qbittorrent",
    "transmission", "sabnzbd", "sonarr", "radarr", "lidarr", "prowlarr", "bazarr", "nextcloud",
    "frigate", "music_assistant", "whisper", "piper", "hacs",
})

# Backup add-ons: RX that is not just TCP ACKs of the upload is the snapshot pull from the Supervisor.
BACKUP_ACK_OVERHEAD = 0.04
# Tunnel add-ons: every proxied byte crosses the container's interface twice (WAN hop + hassio hop).
TUNNEL_WAN_SHARE = 0.5

CORE_KEY = "homeassistant"
CORE_NAME = "Home Assistant Core (integrations, updates)"

PANEL_URL = "mikrotik-usage"
STATIC_URL = "/mikrotik_usage_static/mikrotik-usage-panel.js"
