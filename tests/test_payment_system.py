import pytest
import json
from datetime import datetime, timezone, timedelta
from decimal import Decimal
from urllib.parse import quote_plus

from app.models import Payment, User, Invitation, Settings
from app.services.kofi import KofiService
from app.extensions import db


@pytest.fixture
def sample_user(app):
    """Create a sample user for testing.""" 
    user = None
    with app.app_context():
        user = User(
            token="test_token",
            username="testuser",
            email="test@example.com",
            code="test_code",
            expires=datetime.now(timezone.utc) - timedelta(days=1)  # Expired user
        )
        db.session.add(user)
        db.session.commit()
        user_id = user.id
        
    yield user
    
    # Clean up
    with app.app_context():
        # Clean up any payments first to avoid foreign key constraints
        Payment.query.filter_by(user_id=user_id).delete()
        user = db.session.get(User, user_id)
        if user:
            db.session.delete(user)
        db.session.commit()


@pytest.fixture
def sample_invitation(app, sample_user):
    """Create a sample invitation linked to a user."""
    with app.app_context():
        # Get user by ID to avoid session conflicts
        user = db.session.get(User, sample_user.id)
        invitation = Invitation(
            code="TESTINVITE123",
            used=True,
            used_by=user,
            expires=datetime.now(timezone.utc) + timedelta(days=30)
        )
        db.session.add(invitation)
        db.session.commit()
        invitation_id = invitation.id
        
    yield invitation
    
    with app.app_context():
        invitation = db.session.get(Invitation, invitation_id)
        if invitation:
            db.session.delete(invitation)
            db.session.commit()


@pytest.fixture
def kofi_settings(app):
    """Create Ko-fi settings for testing."""
    with app.app_context():
        # Clean up any existing Ko-fi settings first
        Settings.query.filter(Settings.key.like('kofi_%')).delete()
        db.session.commit()
        
        settings = [
            Settings(key="kofi_account_url", value="https://ko-fi.com/testuser"),
            Settings(key="kofi_verification_token", value="test-token-123"),
            Settings(key="kofi_1_month_price", value="5.00"),
            Settings(key="kofi_3_month_price", value="12.00"),
            Settings(key="kofi_6_month_price", value="20.00")
        ]
        for setting in settings:
            db.session.add(setting)
        db.session.commit()
        yield settings
        
        # Clean up
        Settings.query.filter(Settings.key.like('kofi_%')).delete()
        db.session.commit()


@pytest.fixture
def admin_user(app):
    """Create admin user settings for testing."""
    with app.app_context():
        # Clean up any existing admin settings first
        Settings.query.filter(Settings.key.in_(['admin_username', 'admin_password'])).delete()
        db.session.commit()
        
        settings = [
            Settings(key="admin_username", value="admin"),
            Settings(key="admin_password", value="scrypt:32768:8:1$test$hashedpassword")
        ]
        for setting in settings:
            db.session.add(setting)
        db.session.commit()
        yield settings
        
        # Clean up
        Settings.query.filter(Settings.key.in_(['admin_username', 'admin_password'])).delete()
        db.session.commit()


class TestKofiService:
    """Test the KofiService class."""

    def test_get_kofi_settings(self, app, kofi_settings):
        """Test getting Ko-fi settings from database."""
        with app.app_context():
            settings = KofiService.get_kofi_settings()
            
            assert settings['kofi_account_url'] == "https://ko-fi.com/testuser"
            assert settings['kofi_verification_token'] == "test-token-123"
            assert settings['kofi_1_month_price'] == "5.00"
            assert settings['kofi_3_month_price'] == "12.00"
            assert settings['kofi_6_month_price'] == "20.00"

    def test_get_kofi_settings_empty(self, app):
        """Test getting Ko-fi settings when none exist."""
        with app.app_context():
            settings = KofiService.get_kofi_settings()
            
            assert settings['kofi_account_url'] == ""
            assert settings['kofi_verification_token'] == ""
            assert settings['kofi_1_month_price'] == ""
            assert settings['kofi_3_month_price'] == ""
            assert settings['kofi_6_month_price'] == ""

    def test_verify_webhook_token_valid(self, app, kofi_settings):
        """Test webhook token verification with valid token."""
        with app.app_context():
            assert KofiService.verify_webhook_token("test-token-123") is True

    def test_verify_webhook_token_invalid(self, app, kofi_settings):
        """Test webhook token verification with invalid token."""
        with app.app_context():
            assert KofiService.verify_webhook_token("wrong-token") is False

    def test_verify_webhook_token_no_setting(self, app):
        """Test webhook token verification when no token is configured."""
        with app.app_context():
            assert KofiService.verify_webhook_token("any-token") is False

    def test_parse_webhook_data_valid(self, app):
        """Test parsing valid Ko-fi webhook data."""
        with app.app_context():
            # Sample Ko-fi webhook data
            webhook_data = {
                "message_id": "3a1fac0c-f960-4506-a60e-824979a74e74",
                "kofi_transaction_id": "0a1fac0c-f960-4506-a60e-824979a74e71",
                "timestamp": "2022-08-21T13:04:30Z",
                "type": "Donation",
                "from_name": "Ko-fi Team",
                "message": "test@example.com - Good luck!",
                "amount": "5.00",
                "currency": "USD",
                "url": "https://ko-fi.com",
                "is_subscription_payment": False,
                "is_first_subscription_payment": False,
                "is_public": True
            }
            
            # URL encode the JSON data as Ko-fi sends it
            form_data = quote_plus(json.dumps(webhook_data))
            
            parsed = KofiService.parse_webhook_data(form_data)
            
            assert parsed is not None
            assert parsed['message_id'] == webhook_data['message_id']
            assert parsed['amount'] == "5.00"
            assert parsed['from_name'] == "Ko-fi Team"

    def test_parse_webhook_data_invalid_json(self, app):
        """Test parsing invalid JSON webhook data."""
        with app.app_context():
            invalid_data = "invalid json data"
            parsed = KofiService.parse_webhook_data(invalid_data)
            assert parsed is None

    def test_parse_webhook_data_missing_fields(self, app):
        """Test parsing webhook data with missing required fields."""
        with app.app_context():
            incomplete_data = {"message_id": "123"}
            form_data = quote_plus(json.dumps(incomplete_data))
            
            parsed = KofiService.parse_webhook_data(form_data)
            assert parsed is None

    def test_determine_extension_months(self, app, kofi_settings):
        """Test determining extension months based on payment amount."""
        with app.app_context():
            assert KofiService.determine_extension_months("5.00") == 1
            assert KofiService.determine_extension_months("12.00") == 3
            assert KofiService.determine_extension_months("20.00") == 6
            assert KofiService.determine_extension_months("999.00") is None

    def test_determine_extension_months_invalid_amount(self, app, kofi_settings):
        """Test determining extension months with invalid amount."""
        with app.app_context():
            assert KofiService.determine_extension_months("invalid") is None
            assert KofiService.determine_extension_months("") is None

    def test_process_payment_success(self, app, sample_user, kofi_settings):
        """Test successful payment processing."""
        with app.app_context():
            payment_data = {
                "message_id": "test-message-123",
                "kofi_transaction_id": "test-transaction-123",
                "amount": "5.00",
                "currency": "USD",
                "from_name": "Test User",
                "message": "test@example.com - Payment for extension"
            }
            
            # Merge user to current session and get original expiry
            user = db.session.merge(sample_user)
            original_expiry = user.expires
            
            success, message = KofiService.process_payment(user.id, payment_data, 1)
            
            assert success is True
            assert "extended by 1 months" in message
            
            # Check that user expiry was updated
            db.session.refresh(user)
            # Handle timezone-naive comparison - ensure both have timezone info
            if original_expiry and not original_expiry.tzinfo:
                original_expiry = original_expiry.replace(tzinfo=timezone.utc)
            current_expiry = user.expires
            if current_expiry and not current_expiry.tzinfo:
                current_expiry = current_expiry.replace(tzinfo=timezone.utc)
            assert current_expiry > original_expiry
            
            # Check that payment record was created
            payment = Payment.query.filter_by(kofi_transaction_id="test-transaction-123").first()
            assert payment is not None
            assert payment.user_id == user.id
            assert payment.extension_months == 1
            assert payment.processed is True

    def test_process_payment_duplicate(self, app, sample_user, kofi_settings):
        """Test processing duplicate payment."""
        with app.app_context():
            payment_data = {
                "message_id": "test-message-456",
                "kofi_transaction_id": "test-transaction-456",
                "amount": "5.00",
                "currency": "USD",
                "from_name": "Test User",
                "message": "test@example.com - Payment for extension"
            }
            
            # Merge user to current session
            user = db.session.merge(sample_user)
            
            # Process payment first time
            success1, message1 = KofiService.process_payment(user.id, payment_data, 1)
            assert success1 is True
            
            # Try to process same payment again
            success2, message2 = KofiService.process_payment(user.id, payment_data, 1)
            assert success2 is False
            assert "already processed" in message2

    def test_process_payment_user_not_found(self, app, kofi_settings):
        """Test processing payment for non-existent user."""
        with app.app_context():
            payment_data = {
                "message_id": "test-message-789",
                "kofi_transaction_id": "test-transaction-789",
                "amount": "5.00",
                "currency": "USD",
                "from_name": "Test User",
                "message": "test@example.com - Payment for extension"
            }
            
            success, message = KofiService.process_payment(99999, payment_data, 1)
            assert success is False
            assert "User not found" in message

    def test_find_user_by_email(self, app, sample_user):
        """Test finding user by email address."""
        with app.app_context():
            # Merge user to current session  
            user = db.session.merge(sample_user)
            
            found_user = KofiService.find_user_by_email("test@example.com")
            assert found_user is not None
            assert found_user.id == user.id
            
            not_found = KofiService.find_user_by_email("nonexistent@example.com")
            assert not_found is None


class TestPaymentWebhook:
    """Test the Ko-fi webhook endpoint."""

    def test_webhook_success(self, app, client, sample_user, kofi_settings):
        """Test successful webhook processing."""
        with app.app_context():
            # Merge user to current session
            user = db.session.merge(sample_user)
            db.session.commit()
            
            webhook_data = {
                "message_id": "webhook-test-123",
                "kofi_transaction_id": "webhook-transaction-123",
                "timestamp": "2022-08-21T13:04:30Z",
                "type": "Donation",
                "from_name": "Test Supporter",
                "message": "test@example.com - Thanks for the great service!",
                "amount": "5.00",
                "currency": "USD",
                "url": "https://ko-fi.com",
                "is_subscription_payment": False,
                "is_first_subscription_payment": False,
                "is_public": True
            }
            
            form_data = {
                'data': json.dumps(webhook_data),
                'verification_token': 'test-token-123'
            }
            
            response = client.post('/payment/kofi-webhook', data=form_data)
            
            assert response.status_code == 200
            assert response.data == b"OK"
            
            # Verify payment was processed
            payment = Payment.query.filter_by(kofi_transaction_id="webhook-transaction-123").first()
            assert payment is not None
            assert payment.user_id == user.id

    def test_webhook_no_data(self, app, client):
        """Test webhook with no data."""
        with app.app_context():
            response = client.post('/payment/kofi-webhook', data={})
            assert response.status_code == 400
            assert b"No data" in response.data

    def test_webhook_invalid_token(self, app, client, kofi_settings):
        """Test webhook with invalid verification token."""
        with app.app_context():
            webhook_data = {
                "message_id": "test-123",
                "kofi_transaction_id": "test-123",
                "amount": "5.00",
                "currency": "USD",
                "from_name": "Test",
                "message": "test@example.com"
            }
            
            form_data = {
                'data': json.dumps(webhook_data),
                'verification_token': 'wrong-token'
            }
            
            response = client.post('/payment/kofi-webhook', data=form_data)
            assert response.status_code == 401

    def test_webhook_invalid_amount(self, app, client, sample_user, kofi_settings):
        """Test webhook with invalid payment amount."""
        with app.app_context():
            webhook_data = {
                "message_id": "test-invalid-amount",
                "kofi_transaction_id": "test-invalid-amount",
                "amount": "999.00",  # Not configured price
                "currency": "USD",
                "from_name": "Test",
                "message": "test@example.com"
            }
            
            form_data = {
                'data': json.dumps(webhook_data),
                'verification_token': 'test-token-123'
            }
            
            response = client.post('/payment/kofi-webhook', data=form_data)
            assert response.status_code == 400
            assert b"Invalid amount" in response.data

    def test_webhook_user_not_found(self, app, client, kofi_settings):
        """Test webhook when user email is not found."""
        with app.app_context():
            webhook_data = {
                "message_id": "test-no-user",
                "kofi_transaction_id": "test-no-user",
                "amount": "5.00",
                "currency": "USD",
                "from_name": "Test",
                "message": "nonexistent@example.com - payment"
            }
            
            form_data = {
                'data': json.dumps(webhook_data),
                'verification_token': 'test-token-123'
            }
            
            response = client.post('/payment/kofi-webhook', data=form_data)
            assert response.status_code == 400
            assert b"User not found" in response.data


class TestPaymentSettings:
    """Test the payment settings form and routes."""

    def test_payment_settings_get(self, app, client, admin_user):
        """Test accessing payment settings page."""
        with app.app_context():
            # Login as admin first
            with client.session_transaction() as sess:
                sess['_user_id'] = 'admin'
                sess['_fresh'] = True
            
            response = client.get('/settings/payment', 
                                headers={'HX-Request': 'true'})
            
            assert response.status_code == 200
            assert b"Ko-fi Payment Setup" in response.data
            assert b"kofi_verification_token" in response.data

    def test_payment_settings_post_success(self, app, client, admin_user):
        """Test saving payment settings successfully."""
        with app.app_context():
            # Login as admin
            with client.session_transaction() as sess:
                sess['_user_id'] = 'admin'
                sess['_fresh'] = True
            
            form_data = {
                'kofi_account_url': 'https://ko-fi.com/newuser',
                'kofi_verification_token': 'new-test-token',
                'kofi_1_month_price': '6.00',
                'kofi_3_month_price': '15.00',
                'kofi_6_month_price': '25.00'
            }
            
            response = client.post('/settings/payment', 
                                 data=form_data,
                                 headers={'HX-Request': 'true'})
            
            assert response.status_code == 200
            
            # Verify settings were saved
            url_setting = Settings.query.filter_by(key='kofi_account_url').first()
            assert url_setting.value == 'https://ko-fi.com/newuser'
            
            token_setting = Settings.query.filter_by(key='kofi_verification_token').first()
            assert token_setting.value == 'new-test-token'
            
            price_setting = Settings.query.filter_by(key='kofi_1_month_price').first()
            assert price_setting.value == '6.00'

    def test_payment_settings_requires_login(self, app, client):
        """Test that payment settings requires admin login."""
        with app.app_context():
            response = client.get('/settings/payment')
            # Should redirect to login or return 401
            assert response.status_code in [302, 401]


class TestPaymentUI:
    """Test the payment user interface."""

    def test_payment_page_access(self, app, client, sample_user, sample_invitation, kofi_settings):
        """Test that payment page can be accessed."""
        with app.app_context():
            # Simulate user session
            with client.session_transaction() as sess:
                sess['wizard_access'] = 'TESTINVITE123'
            
            response = client.get('/payment/extend-account')
            
            # Test that we get a valid HTTP response
            assert response.status_code in [200, 302]
            # Test that the route exists and responds
            assert response.data is not None

    def test_payment_page_no_user(self, app, client):
        """Test payment page when no user is found."""
        with app.app_context():
            response = client.get('/payment/extend-account')
            
            assert response.status_code == 302  # Redirect
            assert b"Redirect" in response.data or response.location

    def test_payment_status_check(self, app, client, sample_user, sample_invitation):
        """Test payment status check endpoint."""
        with app.app_context():
            # Simulate user session
            with client.session_transaction() as sess:
                sess['wizard_access'] = 'TESTINVITE123'
            
            response = client.get('/payment/check-status')
            
            assert response.status_code == 200
            data = json.loads(response.data)
            assert 'active' in data
            assert 'expires' in data
            assert data['active'] is False  # User is expired

    def test_payment_status_active_user(self, app, client):
        """Test payment status for active user."""
        with app.app_context():
            # Create active user
            active_user = User(
                token="active_token",
                username="activeuser",
                email="active@example.com",
                code="active_code",
                expires=datetime.now(timezone.utc) + timedelta(days=30)  # Active user
            )
            db.session.add(active_user)
            db.session.commit()
            
            # Create invitation for this user
            invitation = Invitation(
                code="ACTIVEINVITE123",
                used=True,
                used_by=active_user,
                expires=datetime.now(timezone.utc) + timedelta(days=30)
            )
            db.session.add(invitation)
            db.session.commit()
            
            # Simulate user session
            with client.session_transaction() as sess:
                sess['wizard_access'] = 'ACTIVEINVITE123'
            
            response = client.get('/payment/check-status')
            
            assert response.status_code == 200
            data = json.loads(response.data)
            assert data['active'] is True

    def test_user_status_page(self, app, client, sample_user, sample_invitation, kofi_settings):
        """Test that user status page displays correctly."""
        with app.app_context():
            # Ensure the invitation and user are properly linked and committed
            user = db.session.merge(sample_user)
            invitation = db.session.merge(sample_invitation)
            
            # Add required settings for the app to work (bypass onboarding middleware)
            server_verified = Settings(key="server_verified", value="true")
            db.session.add(server_verified)
            db.session.commit()
            
            # Debug: Check if invitation exists and is linked to user
            check_invitation = Invitation.query.filter_by(code='TESTINVITE123').first()
            assert check_invitation is not None, "Invitation not found in database"
            assert check_invitation.used_by is not None, "Invitation not linked to user"
            assert check_invitation.used_by.id == user.id, "Invitation linked to wrong user"
            
            # Simulate user session
            with client.session_transaction() as sess:
                sess['wizard_access'] = 'TESTINVITE123'
            
            response = client.get('/my-account')
            
            # Test that we get a valid response
            assert response.status_code == 200
            
            # Check for key elements of the status page
            assert b"My Account" in response.data
            assert b"Subscription Status" in response.data
            
            # Clean up the setting
            Settings.query.filter_by(key="server_verified").delete()
            db.session.commit()


class TestPaymentModels:
    """Test the Payment model."""

    def test_payment_creation(self, app, sample_user):
        """Test creating a Payment record."""
        with app.app_context():
            # Merge user to current session
            user = db.session.merge(sample_user)
            
            payment = Payment(
                user_id=user.id,
                kofi_transaction_id="model-test-123",
                message_id="model-message-123",
                amount="5.00",
                currency="USD",
                from_name="Test User",
                message="Test payment",
                extension_months=1,
                processed=True
            )
            
            db.session.add(payment)
            db.session.commit()
            
            # Verify payment was created
            saved_payment = Payment.query.filter_by(kofi_transaction_id="model-test-123").first()
            assert saved_payment is not None
            assert saved_payment.user_id == user.id
            assert saved_payment.extension_months == 1
            assert saved_payment.processed is True

    def test_payment_user_relationship(self, app, sample_user):
        """Test the relationship between Payment and User."""
        with app.app_context():
            # Merge the user to current session
            user = db.session.merge(sample_user)
            
            payment = Payment(
                user_id=user.id,
                kofi_transaction_id="relationship-test-123",
                message_id="relationship-message-123",
                amount="5.00",
                currency="USD",
                from_name="Test User",
                extension_months=1
            )
            
            db.session.add(payment)
            db.session.commit()
            
            # Refresh relationships
            db.session.refresh(user)
            db.session.refresh(payment)
            
            # Test relationship
            assert payment.user == user
            assert payment in user.payments