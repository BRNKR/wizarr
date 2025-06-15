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
            'kofi_6_month_price',
            'payment_model'
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
        """Process Ko-fi payment and extend user account based on payment model."""
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
            
            # Get payment model setting
            settings = {s.key: s.value for s in Settings.query.all()}
            payment_model = settings.get("payment_model", "per_server")
            
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
            
            # Extend user account(s) based on payment model
            now = datetime.now(timezone.utc)
            users_to_extend = []
            
            if payment_model == "all_servers":
                # Extend all user accounts with the same email across all servers
                users_to_extend = User.query.filter_by(email=user.email).all()
                logging.info(f"Payment model 'all_servers': extending {len(users_to_extend)} accounts for user {user.email}")
            else:
                # Only extend the specific user who made the payment
                users_to_extend = [user]
                logging.info(f"Payment model 'per_server': extending account for user {user.email} on server {user.server.name if user.server else 'unknown'}")
            
            # Extend each user account
            for target_user in users_to_extend:
                user_expires = target_user.expires
                if user_expires and not user_expires.tzinfo:
                    user_expires = user_expires.replace(tzinfo=timezone.utc)
                
                if user_expires and user_expires > now:
                    # User still has time left, extend from current expiry
                    new_expiry = user_expires + timedelta(days=30 * extension_months)
                else:
                    # User is expired or has no expiry, extend from now
                    new_expiry = now + timedelta(days=30 * extension_months)
                
                target_user.expires = new_expiry
                logging.info(f"Extended account for {target_user.email} on server {target_user.server.name if target_user.server else 'unknown'} until {new_expiry.strftime('%Y-%m-%d')}")
            
            # Re-enable user on media server(s) if they were disabled
            try:
                KofiService._reenable_user_media_access(user)
            except Exception as e:
                logging.warning(f"Failed to re-enable media server access for user {user_id}: {e}")
                # Don't fail the entire payment process if re-enabling fails
            
            # Save to database
            db.session.add(payment)
            db.session.commit()
            
            server_count = len(users_to_extend)
            server_text = f"{server_count} server{'s' if server_count > 1 else ''}" if payment_model == "all_servers" else f"server {user.server.name if user.server else 'unknown'}"
            
            logging.info(f"Successfully processed Ko-fi payment for user {user.email}: {extension_months} months extension on {server_text}")
            return True, f"Account extended by {extension_months} months on {server_text}"
            
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
        """Re-enable user access on media server(s) after payment."""
        try:
            settings = {s.key: s.value for s in Settings.query.all()}
            payment_model = settings.get("payment_model", "per_server")
            
            if payment_model == "all_servers":
                # Enable access on all servers user has accounts on
                from app.models import MediaServer
                # Find all servers where this user has an account
                all_users = User.query.filter_by(email=user.email).all()
                servers_to_enable = {u.server for u in all_users if u.server}
                
                for server in servers_to_enable:
                    server_user = next((u for u in all_users if u.server_id == server.id), None)
                    if server_user:
                        KofiService._enable_user_on_server(server_user, server)
                        
            else:
                # Original per-server logic - only enable on user's assigned server
                if user.server:
                    KofiService._enable_user_on_server(user, user.server)
                else:
                    logging.warning(f"User {user.email} has no assigned server")
                    
        except Exception as e:
            logging.error(f"Failed to re-enable media server access for user {user.email}: {e}")
            raise e
    
    @staticmethod
    def _enable_user_on_server(user: User, server) -> None:
        """Enable a specific user on a specific server."""
        try:
            from app.services.media.service import get_client_for_media_server
            client = get_client_for_media_server(server)
            
            # Get libraries for the user (from their original invitation)
            from app.models import Invitation
            invitation = Invitation.query.filter_by(used_by_id=user.id).first()
            libraries = []
            if invitation and invitation.libraries:
                libraries = [lib.external_id for lib in invitation.libraries]
            else:
                # Use default enabled libraries for this server
                from app.models import Library
                libraries = [lib.external_id for lib in Library.query.filter_by(enabled=True, server_id=server.id).all()]
            
            if server.server_type == "plex":
                client.enable_user(user.email, libraries)
                logging.info(f"Re-enabled Plex access for user {user.email} on server {server.name}")
            elif server.server_type in ["jellyfin", "emby", "audiobookshelf"]:
                client.enable_user(user.username, libraries)
                logging.info(f"Re-enabled {server.server_type} access for user {user.username} on server {server.name}")
                
        except Exception as e:
            logging.error(f"Failed to enable user {user.email} on server {server.name}: {e}")
            raise e