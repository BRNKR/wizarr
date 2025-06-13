import logging
from flask import Blueprint, request, jsonify, render_template, session, redirect, url_for, flash
from flask_login import login_required, current_user
from flask_babel import _

from app.services.kofi import KofiService
from app.models import User, Settings

payment_bp = Blueprint("payment", __name__, url_prefix="/payment")


@payment_bp.route("/kofi-webhook", methods=["POST"])
def kofi_webhook():
    """Handle Ko-fi webhook for payment verification."""
    try:
        # Get form data from Ko-fi webhook
        form_data = request.form.get('data')
        if not form_data:
            logging.error("No data received from Ko-fi webhook")
            return "No data", 400
        
        # Parse webhook data
        payment_data = KofiService.parse_webhook_data(form_data)
        if not payment_data:
            return "Invalid data", 400
        
        # Verify webhook authenticity (if verification token is configured)
        verification_token = request.form.get('verification_token')
        if verification_token and not KofiService.verify_webhook_token(verification_token):
            logging.error("Ko-fi webhook verification failed")
            return "Unauthorized", 401
        
        # Determine extension months based on payment amount
        extension_months = KofiService.determine_extension_months(payment_data['amount'])
        if not extension_months:
            logging.error(f"Payment amount {payment_data['amount']} does not match any configured price")
            return "Invalid amount", 400
        
        # Extract user email from message (users need to include their email in Ko-fi message)
        message = payment_data.get('message', '').lower()
        user = None
        
        # Try to find user email in the message
        import re
        email_pattern = r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b'
        emails = re.findall(email_pattern, message)
        
        if emails:
            user = KofiService.find_user_by_email(emails[0])
        
        if not user:
            logging.error(f"Could not find user from Ko-fi payment message: {message}")
            return "User not found", 400
        
        # Process payment and extend user account
        success, message = KofiService.process_payment(user.id, payment_data, extension_months)
        
        if success:
            logging.info(f"Ko-fi payment processed successfully: {message}")
            return "OK", 200
        else:
            logging.error(f"Ko-fi payment processing failed: {message}")
            return "Processing failed", 500
            
    except Exception as e:
        logging.error(f"Ko-fi webhook error: {e}")
        return "Internal error", 500


@payment_bp.route("/extend-account")
def payment_page():
    """Show payment page for expired users."""
    user = None
    
    # Try to get user from wizard session
    if session.get("wizard_access"):
        from app.models import Invitation
        code = session.get("wizard_access")
        invitation = Invitation.query.filter_by(code=code).first()
        if invitation and invitation.used_by:
            user = invitation.used_by
    
    # Try to get user from current_user if authenticated
    elif current_user.is_authenticated and hasattr(current_user, 'id') and current_user.id != 'admin':
        try:
            user_id = int(current_user.id)
            user = User.query.get(user_id)
        except (ValueError, TypeError):
            pass
    
    if not user:
        flash(_("User not found"), "error")
        return redirect(url_for("public.root"))
    
    # Get Ko-fi payment settings
    settings = KofiService.get_kofi_settings()
    
    # Check if Ko-fi is configured
    if not any(settings.values()):
        flash(_("Payment system not configured"), "error")
        return redirect(url_for("public.user_status"))
    
    return render_template("payment/extend-account.html", 
                         user=user, 
                         settings=settings)


@payment_bp.route("/check-status")
def check_payment_status():
    """AJAX endpoint to check if user's payment has been processed."""
    user = None
    
    # Try to get user from wizard session
    if session.get("wizard_access"):
        from app.models import Invitation
        code = session.get("wizard_access")
        invitation = Invitation.query.filter_by(code=code).first()
        if invitation and invitation.used_by:
            user = invitation.used_by
    
    # Try to get user from current_user if authenticated
    elif current_user.is_authenticated and hasattr(current_user, 'id') and current_user.id != 'admin':
        try:
            user_id = int(current_user.id)
            user = User.query.get(user_id)
        except (ValueError, TypeError):
            pass
    
    if not user:
        return jsonify({"error": "User not found"}), 404
    
    # Check if user account has been extended (not expired)
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc)
    
    # Handle timezone-naive datetime comparison
    user_expires = user.expires
    if user_expires and not user_expires.tzinfo:
        user_expires = user_expires.replace(tzinfo=timezone.utc)
    
    is_active = user_expires is None or user_expires > now
    
    return jsonify({
        "active": is_active,
        "expires": user.expires.isoformat() if user.expires else None
    })