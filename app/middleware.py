# app/middleware.py
from flask import request, redirect, url_for, session, g
from flask_login import current_user
from app.models import Settings, User, MediaServer
from datetime import datetime, timezone
import logging

def require_onboarding():
    # Skip middleware for certain paths
    skip_paths = ['/setup', '/static', '/settings', '/payment', '/login', '/admin', '/favicon.ico']
    if any(request.path.startswith(path) for path in skip_paths):
        return
    
    # Check if an admin user exists
    admin_setting = Settings.query.filter_by(key="admin_username").first()
    if not admin_setting or not admin_setting.value:
        return redirect(url_for('setup.onboarding'))
    # Require at least one MediaServer to exist
    if not MediaServer.query.first():
        return redirect(url_for('setup.onboarding'))


def _revoke_expired_user_access(user):
    """Revoke access from media server for expired user."""
    try:
        # Skip if already processed
        if hasattr(user, '_access_revoked') and user._access_revoked:
            return
            
        # Get server type from user's media server
        server = user.server
        if not server:
            logging.warning(f"No server associated with user {user.username}")
            return
            
        server_type = server.server_type
        
        if server_type == "plex":
            from app.services.media.plex import PlexClient
            client = PlexClient(media_server=server)
            # Disable user from Plex server (preserves account for Ko-fi restoration)
            client.disable_user(user.email)
            logging.info(f"Disabled Plex access for expired user: {user.email}")
            
        elif server_type in ["jellyfin", "emby"]:
            from app.services.media.jellyfin import JellyfinClient
            client = JellyfinClient(media_server=server)
            # Disable user from Jellyfin/Emby server (preserves account for Ko-fi restoration)
            client.disable_user(user.token)  # token is the user ID for Jellyfin/Emby
            logging.info(f"Disabled {server_type} access for expired user: {user.username}")
        
        # Mark as processed to avoid repeated revocation attempts
        user._access_revoked = True
            
    except Exception as e:
        logging.error(f"Failed to revoke media server access for user {user.username}: {e}")
        # Don't mark as processed if it failed, so we can retry


def check_user_expiry():
    """Check if current user is expired and redirect to payment page if needed."""
    # Skip middleware for certain paths
    skip_paths = [
        '/setup', '/static', '/admin', '/login', '/payment', '/favicon.ico',
        '/health', '/logout', '/j/', '/', '/my-account'  # invite links, root, and user status
    ]
    if any(request.path.startswith(path) for path in skip_paths):
        return
    
    # Only check expiry for users with active wizard sessions or authenticated users
    # Skip if no wizard access session (not a logged in user)
    if not session.get("wizard_access") and not current_user.is_authenticated:
        return
    
    # Skip for admin users
    if current_user.is_authenticated and hasattr(current_user, 'id') and current_user.id == 'admin':
        return
    
    # Check for regular users with wizard access
    if session.get("wizard_access"):
        # Try to find user by invitation code
        from app.models import Invitation
        code = session.get("wizard_access")
        invitation = Invitation.query.filter_by(code=code).first()
        
        if invitation and invitation.used_by:
            user = invitation.used_by
            
            # Check if user is expired
            if user.expires:
                now = datetime.now(timezone.utc)
                if user.expires < now:
                    # Revoke media server access immediately
                    _revoke_expired_user_access(user)
                    
                    # Check if Ko-fi payment is configured
                    kofi_settings = Settings.query.filter(
                        Settings.key.in_(['kofi_1_month_price', 'kofi_3_month_price', 'kofi_6_month_price'])
                    ).all()
                    
                    if kofi_settings and any(s.value for s in kofi_settings):
                        # Redirect to user status page (which includes payment options)
                        return redirect(url_for('public.user_status'))
    
    # For authenticated regular users (if this system has them)
    if current_user.is_authenticated and hasattr(current_user, 'id') and current_user.id != 'admin':
        try:
            user_id = int(current_user.id)
            user = User.query.get(user_id)
            
            if user and user.expires:
                now = datetime.now(timezone.utc) 
                if user.expires < now:
                    # Revoke media server access immediately
                    _revoke_expired_user_access(user)
                    
                    # Check if Ko-fi payment is configured
                    kofi_settings = Settings.query.filter(
                        Settings.key.in_(['kofi_1_month_price', 'kofi_3_month_price', 'kofi_6_month_price'])
                    ).all()
                    
                    if kofi_settings and any(s.value for s in kofi_settings):
                        # Redirect to user status page (which includes payment options)
                        return redirect(url_for('public.user_status'))
        except (ValueError, TypeError):
            # current_user.id is not a valid integer (probably admin)
            pass
