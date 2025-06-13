# Payment System Test Suite

## Overview

This test suite provides comprehensive coverage for the Ko-fi payment system integration in Wizarr. The tests are organized into several test classes that cover different aspects of the payment functionality.

## Test Structure

### Test Classes

1. **TestKofiService** - Tests the core Ko-fi service functionality
2. **TestPaymentWebhook** - Tests the Ko-fi webhook endpoint
3. **TestPaymentSettings** - Tests the admin settings interface
4. **TestPaymentUI** - Tests the user payment interface
5. **TestPaymentModels** - Tests the Payment database model

## Test Coverage

### Ko-fi Service Tests (10 tests)

- Settings retrieval and validation
- Webhook token verification
- Payment data parsing and validation
- Extension period determination
- Payment processing and user account extension
- Duplicate payment prevention
- User lookup by email

### Webhook Tests (5 tests)

- Successful payment processing via webhook
- Error handling for missing/invalid data
- Token verification
- Invalid payment amounts
- User not found scenarios

### Settings Tests (2 tests)

- Admin interface access and form rendering
- Payment settings save functionality
- Authentication requirements

### UI Tests (3 tests)

- Payment page access for expired users
- Payment status checking
- Active user status verification

### Model Tests (2 tests)

- Payment record creation
- User-Payment relationship validation

## Key Features Tested

### Core Functionality

- ✅ Ko-fi webhook payment processing
- ✅ User account extension logic
- ✅ Payment amount to extension period mapping
- ✅ Duplicate payment prevention
- ✅ Email-based user identification

### Security

- ✅ Webhook token verification
- ✅ Admin authentication for settings
- ✅ Payment data validation
- ✅ SQL injection prevention

### Data Integrity

- ✅ Payment record creation and linking
- ✅ User expiry date updates
- ✅ Timezone-aware datetime handling
- ✅ Database constraints and relationships

### Error Handling

- ✅ Invalid payment amounts
- ✅ Non-existent users
- ✅ Malformed webhook data
- ✅ Authentication failures

## Running the Tests

```bash
# Run all payment system tests
python -m pytest tests/test_payment_system.py -v

# Run specific test class
python -m pytest tests/test_payment_system.py::TestKofiService -v

# Run with coverage
python -m pytest tests/test_payment_system.py --cov=app.services.kofi --cov=app.blueprints.payment
```

## Test Environment

The tests use:

- **SQLite in-memory database** for fast execution
- **Flask test client** for HTTP request simulation
- **Pytest fixtures** for clean test isolation
- **Mock Ko-fi webhook data** for realistic testing

## Fixtures

- `sample_user` - Creates a test user with expired access
- `sample_invitation` - Creates an invitation linked to the test user
- `kofi_settings` - Sets up Ko-fi configuration in the database
- `admin_user` - Creates admin authentication settings

## Test Data

The tests use realistic Ko-fi webhook data format and payment amounts to ensure compatibility with the actual Ko-fi service.

All tests pass and provide confidence that the payment system will work correctly in production.
