import os

# Default save directory (following XDG specs)
SAVE_DIR = os.path.join(os.environ.get('XDG_CACHE_HOME', os.path.expanduser('~/.cache')), 'hy3dgen', 'archeon')
os.makedirs(SAVE_DIR, exist_ok=True)


def get_job_db_path() -> str | None:
    """Path to the SQLite job store, or None to disable persistence.

    Set ``ARCHEON_JOB_DB`` to override the default location
    (``$XDG_STATE_HOME/hy3dgen/archeon/jobs.db``). Set it to the empty
    string to disable persistence entirely (the manager will run
    in-memory only, same as before this feature was added).
    """
    explicit = os.environ.get('ARCHEON_JOB_DB')
    if explicit is not None:
        if explicit == '':
            return None
        return explicit
    return os.path.join(
        os.environ.get('XDG_STATE_HOME', os.path.expanduser('~/.local/state')),
        'hy3dgen', 'archeon', 'jobs.db',
    )


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



def get_log_level() -> str:
    """Log level from ``ARCHEON_LOG_LEVEL`` (default ``INFO``)."""
    return os.environ.get('ARCHEON_LOG_LEVEL', 'INFO').upper()


def get_log_file() -> str | None:
    """Optional log file path from ``ARCHEON_LOG_FILE``.

    Empty string disables file logging (stderr only, the default).
    """
    explicit = os.environ.get('ARCHEON_LOG_FILE')
    if explicit is None or explicit == '':
        return None
    return explicit



def get_bind_host() -> str:
    """Bind host for the API server.

    Precedence (highest first):
        1. ``ARCHEON_HOST`` env var (explicit override; default unset).
        2. If ``ARCHEON_API_KEY`` is set: ``0.0.0.0`` (you've opted in
           to expose the API beyond localhost).
        3. Otherwise: ``127.0.0.1`` (dev / untrusted default).
    """
    explicit = os.environ.get('ARCHEON_HOST')
    if explicit:
        return explicit
    if os.environ.get('ARCHEON_API_KEY'):
        return '0.0.0.0'
    return '127.0.0.1'
def get_bind_port() -> int:
    """Bind port from ``ARCHEON_PORT`` (default ``8081``)."""
    try:
        return int(os.environ.get('ARCHEON_PORT', '8081'))
    except ValueError:
        return 8081


def configure_logging() -> None:
    """Set up root logging once on startup.

    Honours ``ARCHEON_LOG_LEVEL`` (DEBUG / INFO / WARNING / ERROR) and
    ``ARCHEON_LOG_FILE`` (optional file path with rotation at 50 MB,
    keeping 5 backups). Idempotent: safe to call from tests too.
    """
    import logging
    import logging.handlers
    level = get_log_level()
    handlers: list[logging.Handler] = [logging.StreamHandler()]
    log_file = get_log_file()
    if log_file:
        from pathlib import Path
        Path(log_file).parent.mkdir(parents=True, exist_ok=True)
        handlers.append(
            logging.handlers.RotatingFileHandler(
                log_file, maxBytes=50 * 1024 * 1024, backupCount=5,
                encoding='utf-8',
            )
        )
    fmt = '%(asctime)s %(levelname)-7s [%(name)s] %(message)s'
    logging.basicConfig(
        level=level,
        format=fmt,
        datefmt='%Y-%m-%d %H:%M:%S',
        handlers=handlers,
        force=True,
    )
