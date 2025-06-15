from flask import Blueprint, render_template, request, redirect, session, url_for, flash, jsonify
from werkzeug.security import check_password_hash
from app.models import Settings, AdminUser, Invitation, User, MediaServer
from app.extensions import db
from app.services.media.service import get_client_for_media_server
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
    """User login using email-based authentication."""
    if request.method == "GET":
        # Get admin email setting
        admin_email_setting = Settings.query.filter_by(key="admin_email").first()
        admin_email = admin_email_setting.value if admin_email_setting else None
        
        # Get server logo URL setting
        server_logo_setting = Settings.query.filter_by(key="server_logo_url").first()
        server_logo_url = server_logo_setting.value if server_logo_setting else None
        
        return render_template("user-login.html", admin_email=admin_email, server_logo_url=server_logo_url)
    
    return _handle_email_login()


@auth_bp.route("/api/detect-auth-method", methods=["POST"])
def detect_auth_method():
    """API endpoint to detect authentication method for an email."""
    data = request.get_json()
    email = data.get("email", "").strip().lower()
    
    if not email or "@" not in email:
        return jsonify({"auth_method": "none"})
    
    # Find user by email
    user = User.query.filter(User.email.ilike(email)).first()
    
    if not user or not user.server:
        return jsonify({"auth_method": "none"})
    
    # Return authentication method based on server type
    if user.server.server_type == "plex":
        return jsonify({"auth_method": "plex"})
    elif user.server.server_type in ["jellyfin", "emby", "audiobookshelf"]:
        return jsonify({"auth_method": "password"})
    else:
        return jsonify({"auth_method": "none"})


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


def _handle_email_login():
    """Handle email-based login with automatic server detection."""
    email = request.form.get("email", "").strip()
    password = request.form.get("password", "").strip()
    token = request.form.get("token", "").strip()  # For Plex OAuth
    selected_server_id = request.form.get("selected_server_id")
    
    if not email:
        flash(_("Email address is required."), "error")
        return redirect(url_for("auth.user_login"))
    
    # Find all users with this email across all servers
    users = User.query.filter(User.email.ilike(email)).all()
    
    if not users:
        flash(_("No account found with that email address."), "error")
        return redirect(url_for("auth.user_login"))
    
    # Group users by server
    servers = {}
    for user in users:
        if user.server:
            servers[user.server.id] = {
                "server": user.server,
                "user": user
            }
    
    # If specific server was selected, authenticate with that server
    if selected_server_id:
        try:
            server_id = int(selected_server_id)
            if server_id not in servers:
                flash(_("Invalid server selection."), "error")
                return redirect(url_for("auth.user_login"))
            
            return _authenticate_with_server(servers[server_id], password, token)
                
        except ValueError:
            flash(_("Invalid server selection."), "error")
            return redirect(url_for("auth.user_login"))
    
    # If multiple servers found, show server selection
    elif len(servers) > 1:
        # Get admin email and logo for template
        admin_email_setting = Settings.query.filter_by(key="admin_email").first()
        admin_email = admin_email_setting.value if admin_email_setting else None
        
        server_logo_setting = Settings.query.filter_by(key="server_logo_url").first()
        server_logo_url = server_logo_setting.value if server_logo_setting else None
        
        # Return server selection page
        return render_template(
            "user-login.html",
            servers=list(servers.values()),
            email=email,
            password=password,
            show_server_selection=True,
            admin_email=admin_email,
            server_logo_url=server_logo_url
        )
    
    # Single server found - authenticate directly
    else:
        server_info = list(servers.values())[0]
        return _authenticate_with_server(server_info, password, token)


def _authenticate_with_server(server_info, password, token):
    """Authenticate user with a specific server."""
    server = server_info["server"]
    user = server_info["user"]
    
    # Get admin email and logo for error cases
    admin_email_setting = Settings.query.filter_by(key="admin_email").first()
    admin_email = admin_email_setting.value if admin_email_setting else None
    
    server_logo_setting = Settings.query.filter_by(key="server_logo_url").first()
    server_logo_url = server_logo_setting.value if server_logo_setting else None
    
    # Handle authentication based on server type
    if server.server_type == "plex":
        # Handle Plex OAuth
        if not token:
            flash(_("Plex authentication required. Please use Plex sign-in."), "error")
            return redirect(url_for("auth.user_login"))
        
        try:
            from plexapi.myplex import MyPlexAccount
            account = MyPlexAccount(token=token)
            
            # Verify the token belongs to this user
            if account.email.lower() != user.email.lower():
                flash(_("Plex account does not match registered email."), "error")
                return redirect(url_for("auth.user_login"))
                
            # Update user's token
            user.token = token
            db.session.commit()
            
        except Exception as e:
            logging.error(f"Plex authentication error: {e}")
            flash(_("Plex authentication failed. Please try again."), "error")
            return redirect(url_for("auth.user_login"))
    
    elif server.server_type in ["jellyfin", "emby", "audiobookshelf"]:
        # Handle password-based authentication
        if not password:
            flash(_("Password is required for this server."), "error")
            return redirect(url_for("auth.user_login"))
        
        try:
            client = get_client_for_media_server(server)
            
            # Use username from the user record for authentication
            if not client.validate_user_credentials(user.username, password):
                flash(_("Invalid credentials."), "error")
                return redirect(url_for("auth.user_login"))
                
        except Exception as e:
            logging.error(f"Authentication error: {e}")
            flash(_("Authentication failed. Please try again."), "error")
            return redirect(url_for("auth.user_login"))
    
    else:
        flash(_("Unsupported server type."), "error")
        return redirect(url_for("auth.user_login"))
    
    # Authentication successful - set session
    session["wizard_access"] = user.code
    flash(_("Successfully signed in!"), "success")
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
