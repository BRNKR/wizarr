import datetime
import traceback
import os

from flask import Blueprint, jsonify, request
from app.models import User, Invitation, MediaServer, Identity

status_bp = Blueprint("status", __name__, url_prefix="/api")

API_KEY = os.environ.get("WIZARR_API_KEY")

@status_bp.route("/status", methods=["GET"])
def status():
    # Require API key and can not be blank or empty space
    auth_key = request.headers.get("X-API-Key")
    if not API_KEY or API_KEY.strip() == "" or not auth_key or auth_key != API_KEY:
        return jsonify({"error": "Unauthorized"}), 401

    try:
        now = datetime.datetime.now()
        # Total users
        users = User.query.count()
        # Total invites
        invites = Invitation.query.count()
        # Pending = not used and not expired
        pending = Invitation.query.filter(
            Invitation.used == False,
            (Invitation.expires == None) | (Invitation.expires >= now)
        ).count()
        # Expired if invitation time less than now
        expired = Invitation.query.filter(
            Invitation.expires != None,
            Invitation.expires < now
        ).count()

        return jsonify({
            "users": users,
            "invites": invites,
            "pending": pending,
            "expired": expired
        })

    except Exception as e:
        traceback.print_exc()
        return jsonify({"error": str(e)}), 500


@status_bp.route("/detect-server", methods=["POST"])
def detect_server():
    """Detect which servers a user has access to based on email/username."""
    try:
        data = request.get_json()
        if not data or not data.get("email_username"):
            return jsonify({"error": "email_username is required"}), 400
        
        email_username = data["email_username"].strip()
        
        # Find all users matching this email or username across all servers
        matching_users = []
        
        # Search by email (for Plex users and others with email)
        if "@" in email_username:
            users_by_email = User.query.filter(User.email.ilike(email_username)).all()
            matching_users.extend(users_by_email)
        
        # Search by username (for Jellyfin/Emby users)
        users_by_username = User.query.filter(User.username.ilike(email_username)).all()
        matching_users.extend(users_by_username)
        
        # Remove duplicates
        unique_users = {user.id: user for user in matching_users}
        users = list(unique_users.values())
        
        if not users:
            return jsonify({
                "found": False,
                "servers": [],
                "requires_password": True,
                "message": "No account found"
            })
        
        # Group users by server and prepare response
        servers = []
        requires_password = False
        
        for user in users:
            if user.server:
                server_info = {
                    "id": user.server.id,
                    "name": user.server.name,
                    "type": user.server.server_type,
                    "user_id": user.id,
                    "username": user.username,
                    "email": user.email
                }
                
                # Determine if password is required
                if user.server.server_type in ["jellyfin", "emby"]:
                    requires_password = True
                    server_info["requires_password"] = True
                else:
                    server_info["requires_password"] = False
                
                servers.append(server_info)
        
        # Remove duplicate servers (same user might be found multiple ways)
        unique_servers = {s["id"]: s for s in servers}
        servers = list(unique_servers.values())
        
        return jsonify({
            "found": len(servers) > 0,
            "servers": servers,
            "requires_password": requires_password,
            "multiple_servers": len(servers) > 1
        })
        
    except Exception as e:
        traceback.print_exc()
        return jsonify({"error": str(e)}), 500
