from flask import Blueprint, redirect, render_template, send_from_directory, request, jsonify, url_for, session
import os, threading
from app.extensions import db
from app.models import Settings, Invitation, MediaServer
from app.services.invites import is_invite_valid
from app.services.media.plex import handle_oauth_token
from app.services.ombi_client import run_all_importers
from app.forms.join import JoinForm

public_bp = Blueprint("public", __name__)

# ─── Landing “/” ──────────────────────────────────────────────────────────────
@public_bp.route("/")
def root():
    # check if admin_username exists
    admin_setting = Settings.query.filter_by(key="admin_username").first()
    if not admin_setting:
        return redirect("/setup/")              # installation wizard
    return redirect("/user-login")

# ─── Favicon ─────────────────────────────────────────────────────────────────
@public_bp.route("/favicon.ico")
def favicon():
    return send_from_directory(
        public_bp.root_path.replace("blueprints/public", "static"),
        "favicon.ico",
        mimetype="image/vnd.microsoft.icon",
    )

# ─── Invite link  /j/<code> ─────────────────────────────────────────────────
@public_bp.route("/j/<code>")
def invite(code):
    invitation = Invitation.query.filter(
        db.func.lower(Invitation.code) == code.lower()
    ).first()
    valid, msg = is_invite_valid(code)
    if not valid:
        return render_template("invalid-invite.html", error=msg)

    server = invitation.server or MediaServer.query.first()
    server_type = server.server_type if server else None

    if server_type in ("jellyfin", "emby", "audiobookshelf"):
        form = JoinForm()
        form.code.data = code
        
        # Get server logo URL
        server_logo_setting = Settings.query.filter_by(key="server_logo_url").first()
        server_logo_url = server_logo_setting.value if server_logo_setting else None
        
        return render_template(
            "welcome-jellyfin.html",
            form=form,
            server_type=server_type,
            server_logo_url=server_logo_url,
        )
    
    # Get server logo URL for Plex login too
    server_logo_setting = Settings.query.filter_by(key="server_logo_url").first()
    server_logo_url = server_logo_setting.value if server_logo_setting else None
    
    return render_template("user-plex-login.html", code=code, server_logo_url=server_logo_url)

# ─── POST /join  (Plex OAuth or Jellyfin signup) ────────────────────────────
@public_bp.route("/join", methods=["POST"])
def join():
    code  = request.form.get("code")
    token = request.form.get("token")

    print("Got Token: ", token)

    invitation = Invitation.query.filter(
        db.func.lower(Invitation.code) == code.lower()
    ).first()
    valid, msg = is_invite_valid(code)
    if not valid:
        # server_name for rendering error
        name_setting = Settings.query.filter_by(key="server_name").first()
        server_name = name_setting.value if name_setting else None

        return render_template(
            "user-plex-login.html",
            name=server_name,
            code=code,
            code_error=msg
        )

    server = invitation.server or MediaServer.query.first()
    server_type = server.server_type if server else None

    from flask import current_app
    app = current_app._get_current_object()
    
    if server_type == "plex":
        # run Plex OAuth in background
        threading.Thread(
            target=handle_oauth_token,
            args=(app, token, code),
            daemon=True
        ).start()
        session["wizard_access"] = code
        return redirect(url_for("wizard.start"))
    elif server_type in ("jellyfin", "emby", "audiobookshelf"):
        return render_template("welcome-jellyfin.html", code=code, server_type=server_type)

    # fallback if server_type missing/unsupported
    return render_template("invalid-invite.html", error="Configuration error.")

@public_bp.route("/health", methods=["GET"])
def health():
    # If you need to check DB connectivity, do it here.
    return jsonify(status="ok"), 200


@public_bp.route("/debug-session", methods=["GET"])
def debug_session():
    """Debug route to check session status - remove in production."""
    from app.models import Invitation
    
    debug_info = {
        "session_wizard_access": session.get("wizard_access"),
        "session_keys": list(session.keys()),
    }
    
    # Check invitation if wizard_access exists
    if session.get("wizard_access"):
        code = session.get("wizard_access")
        invitation = Invitation.query.filter_by(code=code).first()
        if invitation:
            debug_info.update({
                "invitation_found": True,
                "invitation_used": invitation.used,
                "invitation_used_by_id": invitation.used_by.id if invitation.used_by else None,
                "invitation_used_by_email": invitation.used_by.email if invitation.used_by else None,
                "invitation_expires": invitation.expires.isoformat() if invitation.expires else None,
            })
        else:
            debug_info["invitation_found"] = False
    
    return jsonify(debug_info)


@public_bp.route("/my-account")
def user_status():
    """User status page showing subscription info and payment options."""
    user = None
    invitation = None
    
    # Try to get user from wizard session
    if session.get("wizard_access"):
        from app.models import Invitation
        code = session.get("wizard_access")
        invitation = Invitation.query.filter_by(code=code).first()
        
        if not invitation:
            # Session has invalid invitation code
            session.pop("wizard_access", None)
            from flask import flash
            from flask_babel import _
            flash(_("Your session has expired. Please use your invitation link again."), "error")
            return redirect(url_for("public.root"))
        
        if invitation and invitation.used_by:
            user = invitation.used_by
        elif invitation:
            # Check if there's a user associated with this invitation code even if used_by isn't set
            # This handles cases where background processes haven't completed yet
            from app.models import User
            user = User.query.filter_by(code=code).first()
            
            if not user:
                # No user found - user hasn't completed signup yet
                from flask import flash
                from flask_babel import _
                flash(_("Please complete your account setup first."), "info")
                return redirect(url_for("wizard.start"))
    
    if not user:
        # No wizard session - redirect to user login
        from flask import flash
        from flask_babel import _
        flash(_("Please sign in with your invitation code to access your account."), "info")
        return redirect(url_for("auth.user_login"))
    
    # Get Ko-fi payment settings to show payment options
    from app.services.kofi import KofiService
    kofi_settings = KofiService.get_kofi_settings()
    payment_available = any(kofi_settings.values())
    
    # Get user's payment history
    from app.models import Payment
    payments = Payment.query.filter_by(user_id=user.id).order_by(Payment.created_at.desc()).all()
    
    # Calculate subscription status
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc)
    
    # Handle timezone-naive datetime comparison
    user_expires = user.expires
    if user_expires and not user_expires.tzinfo:
        user_expires = user_expires.replace(tzinfo=timezone.utc)
    
    is_active = user_expires is None or user_expires > now
    days_remaining = None
    
    if user_expires and is_active:
        days_remaining = (user_expires - now).days
    
    return render_template("user-status.html", 
                         user=user,
                         invitation=invitation,
                         is_active=is_active,
                         days_remaining=days_remaining,
                         user_expires=user_expires,
                         payments=payments,
                         payment_available=payment_available,
                         kofi_settings=kofi_settings)