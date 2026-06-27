from __future__ import annotations

import json


def parse_clients(inbound: dict) -> list:
    if not inbound:
        return []
    settings = inbound.get("settings", "")
    if not settings:
        return []
    if isinstance(settings, str):
        try:
            settings = json.loads(settings)
        except Exception:
            return []
    if not isinstance(settings, dict):
        return []
    clients = settings.get("clients", [])
    return clients if isinstance(clients, list) else []


def parse_stream_settings(inbound: dict) -> dict:
    ss = inbound.get("streamSettings")
    if not ss:
        return {}
    if isinstance(ss, str):
        try:
            return json.loads(ss)
        except Exception:
            return {}
    return ss if isinstance(ss, dict) else {}


def get_client_stats_map(inbound: dict) -> dict:
    stats = {}
    for s in inbound.get("clientStats", []):
        stats[s.get("email", "")] = s
    return stats
