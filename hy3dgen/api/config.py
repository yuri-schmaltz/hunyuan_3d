import os

# Default save directory (following XDG specs)
SAVE_DIR = os.path.join(os.environ.get('XDG_CACHE_HOME', os.path.expanduser('~/.cache')), 'hy3dgen', 'archeon')
os.makedirs(SAVE_DIR, exist_ok=True)


def get_cors_origins() -> list[str]:
    """Parse ``ARCHEON_CORS_ORIGINS`` into a list of allowed origins.

    Format: comma-separated origins, e.g.
    ``ARCHEON_CORS_ORIGINS=http://localhost:5173,http://localhost:9000``.

    The default ``*`` is preserved for developer convenience, but the CORS
    middleware is wired to disable credentials in that case (the spec
    forbids ``Access-Control-Allow-Origin: *`` together with credentials).
    For production, set an explicit allow-list AND set
    ``ARCHEON_ALLOW_CREDENTIALS=true`` if you actually need cookies/auth
    headers in cross-origin requests.
    """
    raw = os.environ.get('ARCHEON_CORS_ORIGINS', '*').strip()
    if raw == '*':
        return ['*']
    return [origin.strip() for origin in raw.split(',') if origin.strip()]


def get_bind_host() -> str:
    """Default host binding.

    When ``ARCHEON_API_KEY`` is set we assume the server is intended to be
    reachable from outside the host and bind to ``0.0.0.0``. Without an
    API key, default to ``127.0.0.1`` to avoid accidentally exposing an
    unauthenticated instance to the network. Callers can still override
    with ``--host``.
    """
    if os.environ.get('ARCHEON_API_KEY'):
        return '0.0.0.0'
    return '127.0.0.1'
