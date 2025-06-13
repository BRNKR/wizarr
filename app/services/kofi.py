import json
import logging
from datetime import datetime, timedelta, timezone
from urllib.parse import unquote_plus
from typing import Dict, Optional, Tuple

from flask import current_app
from app.extensions import db
from app.models import Settings, Payment, User


class KofiService:
    """Service for handling Ko-fi webhook payments and user account extensions."""
    
    @staticmethod
    def get_kofi_settings() -> Dict[str, str]:
        """Get Ko-fi related settings from database."""
        settings_keys = [
            'kofi_account_url',
            'kofi_username',
            'kofi_verification_token',
            'kofi_1_month_price',
            'kofi_3_month_price', 
            'kofi_6_month_price'
        ]
        
        settings = {}
        for key in settings_keys:
            setting = Settings.query.filter_by(key=key).first()
            settings[key] = setting.value if setting else ''
            
        return settings
    
    @staticmethod
    def verify_webhook_token(verification_token: str) -> bool:
        """Verify that the webhook request is from Ko-fi using verification token."""
        stored_token = Settings.query.filter_by(key='kofi_verification_token').first()
        if not stored_token or not stored_token.value:
            logging.warning("Ko-fi verification token not configured")
            return False
            
        return verification_token == stored_token.value
    
    @staticmethod
    def parse_webhook_data(form_data: str) -> Optional[Dict]:
        """Parse Ko-fi webhook form data and extract payment information."""
        try:
            # Ko-fi sends data as urlencoded form with 'data' field containing JSON
            decoded_data = unquote_plus(form_data)
            payment_data = json.loads(decoded_data)
            
            required_fields = ['message_id', 'kofi_transaction_id', 'amount', 'currency', 'from_name']
            for field in required_fields:
                if field not in payment_data:
                    logging.error(f"Missing required field: {field}")
                    return None
                    
            return payment_data
            
        except (json.JSONDecodeError, ValueError) as e:
            logging.error(f"Failed to parse Ko-fi webhook data: {e}")
            return None
    
    @staticmethod
    def determine_extension_months(amount: str) -> Optional[int]:
        """Determine how many months to extend based on payment amount."""
        settings = KofiService.get_kofi_settings()
        
        try:
            payment_amount = float(amount)
            
            # Check prices for different durations
            if settings['kofi_6_month_price'] and float(settings['kofi_6_month_price']) == payment_amount:
                return 6
            elif settings['kofi_3_month_price'] and float(settings['kofi_3_month_price']) == payment_amount:
                return 3
            elif settings['kofi_1_month_price'] and float(settings['kofi_1_month_price']) == payment_amount:
                return 1
                
        except (ValueError, TypeError):
            logging.error(f"Invalid payment amount: {amount}")
            
        return None
    
    @staticmethod
    def process_payment(user_id: int, payment_data: Dict, extension_months: int) -> Tuple[bool, str]:
        """Process Ko-fi payment and extend user account."""
        try:
            # Check if payment already processed
            existing_payment = Payment.query.filter_by(
                kofi_transaction_id=payment_data['kofi_transaction_id']
            ).first()
            
            if existing_payment:
                return False, "Payment already processed"
            
            # Get user
            user = db.session.get(User, user_id)
            if not user:
                return False, "User not found"
            
            # Create payment record
            payment = Payment(
                user_id=user_id,
                kofi_transaction_id=payment_data['kofi_transaction_id'],
                message_id=payment_data['message_id'],
                amount=payment_data['amount'],
                currency=payment_data['currency'],
                from_name=payment_data['from_name'],
                message=payment_data.get('message', ''),
                extension_months=extension_months,
                processed=True,
                processed_at=datetime.now(timezone.utc)
            )
            
            # Extend user account
            now = datetime.now(timezone.utc)
            # Ensure user.expires is timezone-aware for comparison
            user_expires = user.expires
            if user_expires and not user_expires.tzinfo:
                user_expires = user_expires.replace(tzinfo=timezone.utc)
            
            if user_expires and user_expires > now:
                # User still has time left, extend from current expiry
                new_expiry = user_expires + timedelta(days=30 * extension_months)
            else:
                # User is expired or has no expiry, extend from now
                new_expiry = now + timedelta(days=30 * extension_months)
            
            user.expires = new_expiry
            
            # Re-enable user on media server if they were disabled
            try:
                KofiService._reenable_user_media_access(user)
            except Exception as e:
                logging.warning(f"Failed to re-enable media server access for user {user_id}: {e}")
                # Don't fail the entire payment process if re-enabling fails
            
            # Save to database
            db.session.add(payment)
            db.session.commit()
            
            logging.info(f"Successfully processed Ko-fi payment for user {user_id}: {extension_months} months extension")
            return True, f"Account extended by {extension_months} months until {new_expiry.strftime('%Y-%m-%d')}"
            
        except Exception as e:
            db.session.rollback()
            logging.error(f"Failed to process Ko-fi payment: {e}")
            return False, f"Payment processing failed: {str(e)}"
    
    @staticmethod
    def find_user_by_email(email: str) -> Optional[User]:
        """Find user by email address."""
        return User.query.filter_by(email=email).first()
    
    @staticmethod
    def _reenable_user_media_access(user: User) -> None:
        """Re-enable user access on media server after payment."""
        try:
            # Get server type from settings
            settings = {s.key: s.value for s in Settings.query.all()}
            server_type = settings.get("server_type")
            
            if server_type == "plex":
                from app.services.media.plex import PlexClient
                client = PlexClient()
                # Get libraries for the user (from their original invitation)
                from app.models import Invitation, Library
                invitation = Invitation.query.filter_by(used_by_id=user.id).first()
                libraries = []
                if invitation and invitation.libraries:
                    libraries = [lib.external_id for lib in invitation.libraries]
                else:
                    # Use default enabled libraries
                    libraries = [lib.external_id for lib in Library.query.filter_by(enabled=True).all()]
                
                client.enable_user(user.email, libraries)
                logging.info(f"Re-enabled Plex access for user: {user.email}")
                
            elif server_type in ["jellyfin", "emby"]:
                from app.services.media.jellyfin import JellyfinClient
                client = JellyfinClient()
                # Get libraries for the user (from their original invitation)
                from app.models import Invitation, Library
                invitation = Invitation.query.filter_by(used_by_id=user.id).first()
                libraries = []
                if invitation and invitation.libraries:
                    libraries = [lib.external_id for lib in invitation.libraries]
                else:
                    # Use default enabled libraries
                    libraries = [lib.external_id for lib in Library.query.filter_by(enabled=True).all()]
                
                client.enable_user(user.token, libraries)  # token is the user ID for Jellyfin/Emby
                logging.info(f"Re-enabled {server_type} access for user: {user.username}")
                
        except Exception as e:
            logging.error(f"Failed to re-enable media server access for user {user.username}: {e}")
            raise e