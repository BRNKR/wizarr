"""Facade that dispatches media user management to Plex or Jellyfin."""

from app.extensions import db
from app.models import Settings, User
from .client_base import CLIENTS


def _mode() -> str:
    """
    Reads the 'server_type' setting from the DB.
    Falls back to None if it isn't set.
    """
    return (
        db.session
          .query(Settings.value)
          .filter_by(key="server_type")
          .scalar()
    )


def get_client(server_type: str | None = None, url: str | None = None, token: str | None = None):
    """
    Instantiate the MediaClient for the given server_type, optionally overriding URL/token.
    """
    if server_type is None:
        server_type = _mode()
    try:
        cls = CLIENTS[server_type]
    except KeyError:
        raise ValueError(f"Unsupported media server type: {server_type}")
    client = cls()
    if url:
        client.url = url
    if token:
        client.token = token
    return client


def list_users(clear_cache: bool = False):
    """
    Return current users from the configured media server, syncing local DB as needed.
    """
    client = get_client(_mode())
    # clear cache on clients that support it
    if clear_cache and hasattr(client, 'list_users') and hasattr(client.list_users, 'cache_clear'):
        client.list_users.cache_clear()
    return client.list_users()


def delete_user(db_id: int) -> None:
    """
    Disable a user on the configured media server only (preserving Wizarr DB record for Ko-fi restoration).
    The user remains visible in admin panel and can be manually re-enabled.
    """
    server_type = _mode()
    client = get_client(server_type)
    # clear cache pre- and post-removal if supported
    if hasattr(client, 'list_users') and hasattr(client.list_users, 'cache_clear'):
        client.list_users.cache_clear()

    # lookup local record and perform remote disable only
    user = db.session.get(User, db_id)
    if user:
        if server_type == 'plex':
            email = user.email
            if email and email != 'None':
                client.disable_user(email)  # Disable on Plex server
        else:
            client.disable_user(user.token)  # Disable on Jellyfin/Emby server
        
        # Keep user in Wizarr database - they remain visible in admin panel
        # User expiry date is already managed separately in the admin interface

    if hasattr(client, 'list_users') and hasattr(client.list_users, 'cache_clear'):
        client.list_users.cache_clear()


def scan_libraries(url: str | None = None, token: str | None = None, server_type: str | None = None):
    """
    Fetch available libraries from the media server, given optional credentials or using Settings.
    Returns a mapping of external_id -> display_name.
    """
    client = get_client(server_type, url, token)
    return client.libraries()