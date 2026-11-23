"""Explicit, isolated PostgreSQL connection settings for a future SHERIF Cloud.

This module is not activated by the Windows application or by existing server
settings. A separate SHERIF Supabase project must be provisioned explicitly.
"""
from collections.abc import Mapping
from urllib.parse import parse_qsl, unquote, urlsplit
import os


class CloudConfigurationError(ValueError):
    """Invalid or missing cloud settings; never include connection credentials."""


def connection_url(secrets=None, environ=None):
    """Read only the dedicated SHERIF variable; environment takes precedence."""
    environ = os.environ if environ is None else environ
    value = environ.get('SHERIF_SUPABASE_DATABASE_URL')
    if not value and isinstance(secrets, Mapping):
        value = secrets.get('SHERIF_SUPABASE_DATABASE_URL')
    if not isinstance(value, str) or not value.strip():
        raise CloudConfigurationError('SHERIF Cloud database connection is not configured')
    value = value.strip()
    try:
        parsed = urlsplit(value)
        host = (parsed.hostname or '').lower()
        port = parsed.port
        query = parse_qsl(parsed.query, keep_blank_values=True, strict_parsing=True)
    except ValueError:
        raise CloudConfigurationError('Invalid SHERIF Cloud database connection') from None
    valid_host = (host.endswith('.supabase.co') or host.endswith('.pooler.supabase.com'))
    valid_query = all(key == 'sslmode' and val == 'verify-full' for key, val in query)
    if (parsed.scheme not in ('postgres', 'postgresql') or not valid_host
            or not parsed.username or not parsed.password or not parsed.path.strip('/')
            or parsed.fragment or not valid_query or len(query) > 1
            or (port is not None and not 1 <= port <= 65535)
            or any(c in unquote(parsed.path) for c in '\x00\r\n')):
        raise CloudConfigurationError('Invalid SHERIF Cloud database connection')
    return value


def connect_cloud(secrets=None, environ=None):
    """Connect only to the explicitly configured Supabase project with TLS verification.

    The caller owns the returned connection and transaction. No connection is
    made at import time, and connection failures do not expose the URL.
    """
    url = connection_url(secrets=secrets, environ=environ)
    import psycopg2
    try:
        return psycopg2.connect(url, sslmode='verify-full', connect_timeout=10)
    except psycopg2.Error:
        raise CloudConfigurationError('SHERIF Cloud database connection failed') from None
