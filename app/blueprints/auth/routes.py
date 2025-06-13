from flask import Blueprint, render_template, request, redirect, session, url_for, flash
from werkzeug.security import check_password_hash
from app.models import Settings, AdminUser, Invitation
from app.extensions import db
import os, logging
from flask_babel import _
from flask_login import login_user, logout_user, login_required

auth_bp = Blueprint("auth", __name__)

@auth_bp.route("/login", methods=["GET", "POST"])
def login():
   
    if os.getenv("DISABLE_BUILTIN_AUTH", "").lower() == "true":
        login_user(AdminUser(), remember=bool(request.form.get("remember")))
        return redirect("/")

    if request.method == "GET":
        # Get server logo URL for admin login
        server_logo_setting = Settings.query.filter_by(key="server_logo_url").first()
        server_logo_url = server_logo_setting.value if server_logo_setting else None
        
        return render_template("login.html", server_logo_url=server_logo_url)

    username = request.form.get("username")
    password = request.form.get("password")

    # fetch the stored admin credentials
    admin_username = (
        db.session
          .query(Settings.value)
          .filter_by(key="admin_username")
          .scalar()
    )
    admin_password_hash = (
        db.session
          .query(Settings.value)
          .filter_by(key="admin_password")
          .scalar()
    )

    if username == admin_username and check_password_hash(admin_password_hash, password):
        # ❑ auto-migrate sha256 → scrypt
        login_user(AdminUser(), remember=bool(request.form.get("remember")))
        return redirect("/admin")

    logging.warning("Failed login for user %s", username)
    
    # Get server logo URL for error case
    server_logo_setting = Settings.query.filter_by(key="server_logo_url").first()
    server_logo_url = server_logo_setting.value if server_logo_setting else None
    
    return render_template("login.html", error=_("Invalid username or password"), server_logo_url=server_logo_url)


@auth_bp.route("/user-login", methods=["GET", "POST"])
def user_login():
    """User login using media server authentication or invitation code."""
    # Get server type for the template
    server_type_setting = Settings.query.filter_by(key="server_type").first()
    server_type = server_type_setting.value if server_type_setting else None
    
    if request.method == "GET":
        # Get admin email setting
        admin_email_setting = Settings.query.filter_by(key="admin_email").first()
        admin_email = admin_email_setting.value if admin_email_setting else None
        
        # Get server logo URL setting
        server_logo_setting = Settings.query.filter_by(key="server_logo_url").first()
        server_logo_url = server_logo_setting.value if server_logo_setting else None
        
        return render_template("user-login.html", server_type=server_type, admin_email=admin_email, server_logo_url=server_logo_url)
    
    login_type = request.form.get("login_type", "code")
    
    if login_type == "plex":
        return _handle_plex_login(server_type)
    elif login_type in ["jellyfin", "emby"]:
        return _handle_jellyfin_emby_login(login_type, server_type)
    else:
        return _handle_code_login(server_type)


def _handle_plex_login(server_type):
    """Handle Plex OAuth login for existing users."""
    token = request.form.get("token")
    
    # Get admin email and logo for template
    admin_email_setting = Settings.query.filter_by(key="admin_email").first()
    admin_email = admin_email_setting.value if admin_email_setting else None
    
    server_logo_setting = Settings.query.filter_by(key="server_logo_url").first()
    server_logo_url = server_logo_setting.value if server_logo_setting else None
    
    if not token:
        return render_template("user-login.html", server_type=server_type, admin_email=admin_email, server_logo_url=server_logo_url,
                             error=_("Plex authentication failed. Please try again."))
    
    # Get email from Plex token to find user
    try:
        from plexapi.myplex import MyPlexAccount
        account = MyPlexAccount(token=token)
        email = account.email
    except Exception:
        return render_template("user-login.html", server_type=server_type, admin_email=admin_email, server_logo_url=server_logo_url,
                             error=_("Failed to verify Plex account. Please try again."))
    
    # Find user by email instead of token
    from app.models import User
    user = User.query.filter_by(email=email).first()
    
    if not user:
        return render_template("user-login.html", server_type=server_type, admin_email=admin_email, server_logo_url=server_logo_url,
                             error=_("No account found with this Plex email. Please contact admin."))
    
    # Find invitation for this user
    invitation = Invitation.query.filter_by(used_by_id=user.id).first()
    
    if not invitation:
        return render_template("user-login.html", server_type=server_type, admin_email=admin_email, server_logo_url=server_logo_url,
                             error=_("Account setup incomplete. Please contact admin."))
    
    # Update user's token to the current one
    user.token = token
    db.session.commit()
    
    # Set wizard access session
    session["wizard_access"] = invitation.code
    flash(_("Successfully signed in with Plex!"), "success")
    
    return redirect(url_for("public.user_status"))


def _handle_jellyfin_emby_login(login_type, server_type):
    """Handle Jellyfin/Emby login for existing users."""
    username = request.form.get("username")
    password = request.form.get("password")
    
    # Get admin email and logo for template
    admin_email_setting = Settings.query.filter_by(key="admin_email").first()
    admin_email = admin_email_setting.value if admin_email_setting else None
    
    server_logo_setting = Settings.query.filter_by(key="server_logo_url").first()
    server_logo_url = server_logo_setting.value if server_logo_setting else None
    
    if not username or not password:
        return render_template("user-login.html", server_type=server_type, admin_email=admin_email, server_logo_url=server_logo_url,
                             error=_("Please enter both username and password."))
    
    # Validate credentials against media server
    if login_type == "jellyfin":
        from app.services.media.jellyfin import JellyfinClient
        client = JellyfinClient()
        is_valid = client.validate_user_credentials(username, password)
    else:  # emby
        from app.services.media.emby import EmbyClient
        client = EmbyClient()
        is_valid = client.validate_user_credentials(username, password)
    
    if not is_valid:
        return render_template("user-login.html", server_type=server_type, admin_email=admin_email, server_logo_url=server_logo_url,
                             error=_("Invalid username or password."))
    
    # Find user by username
    from app.models import User
    user = User.query.filter_by(username=username).first()
    
    if not user:
        return render_template("user-login.html", server_type=server_type, admin_email=admin_email, server_logo_url=server_logo_url,
                             error=_("No account found with this username. Please contact admin."))
    
    # Find invitation for this user
    invitation = Invitation.query.filter_by(used_by_id=user.id).first()
    
    if not invitation:
        return render_template("user-login.html", server_type=server_type, admin_email=admin_email, server_logo_url=server_logo_url,
                             error=_("Account setup incomplete. Please contact admin."))
    
    # Set wizard access session
    session["wizard_access"] = invitation.code
    flash(_("Successfully signed in!"), "success")
    
    return redirect(url_for("public.user_status"))


def _handle_code_login(server_type):
    """Handle invitation code login (fallback method)."""
    invitation_code = request.form.get("invitation_code")
    
    # Get admin email and logo for template
    admin_email_setting = Settings.query.filter_by(key="admin_email").first()
    admin_email = admin_email_setting.value if admin_email_setting else None
    
    server_logo_setting = Settings.query.filter_by(key="server_logo_url").first()
    server_logo_url = server_logo_setting.value if server_logo_setting else None
    
    if not invitation_code:
        return render_template("user-login.html", server_type=server_type, admin_email=admin_email, server_logo_url=server_logo_url,
                             error=_("Please enter your invitation code"))
    
    # Find the invitation
    invitation = Invitation.query.filter_by(code=invitation_code).first()
    
    if not invitation:
        return render_template("user-login.html", server_type=server_type, admin_email=admin_email, server_logo_url=server_logo_url,
                             error=_("Invalid invitation code"))
    
    # Check if invitation is used and has a user
    if not invitation.used or not invitation.used_by:
        flash(_("Please complete your account setup first by using your invitation link."), "info")
        return redirect(url_for("public.invite", code=invitation_code))
    
    # Set wizard access session
    session["wizard_access"] = invitation_code
    flash(_("Successfully signed in!"), "success")
    
    # Redirect to user account page
    return redirect(url_for("public.user_status"))


@auth_bp.route("/logout")
@login_required
def logout():
    """Admin logout route."""
    logout_user()
    flash(_("You have been logged out."), "info")
    return redirect(url_for("auth.user_login"))


@auth_bp.route("/user-logout")
def user_logout():
    """User logout route - clears user session."""
    # Clear the wizard access session
    session.pop("wizard_access", None)
    flash(_("You have been signed out."), "info")
    return redirect(url_for("auth.user_login"))
