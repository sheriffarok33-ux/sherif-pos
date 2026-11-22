"""Opt-in for future central services; no server is enabled by default."""
import json
import sys
from pathlib import Path
from urllib.parse import urlsplit

def connection_dir():
    if getattr(sys, "frozen", False):
        from sherif_paths import data_dir
        return data_dir()
    return Path(__file__).resolve().parent

def server_enabled():
    root = connection_dir()
    try:
        cfg = json.loads((root / 'SHERIF_CONNECTION.json').read_text(encoding='utf-8'))
        actual = (root / 'SERVER_URL.txt').read_text(encoding='utf-8-sig').strip().rstrip('/')
        url = str(cfg.get('server_url') or '').strip().rstrip('/')
        parts = urlsplit(url)
        return cfg.get('enabled') is True and url == actual and parts.scheme == 'https' and bool(parts.hostname) and not parts.username and not parts.password
    except (OSError, ValueError, TypeError, AttributeError):
        return False
