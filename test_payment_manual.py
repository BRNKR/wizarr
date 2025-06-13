#!/usr/bin/env python3
"""
Manual test script for Ko-fi payment system
Run this while the dev server is running on port 5001
"""

import requests
import json
import sys

BASE_URL = "http://127.0.0.1:5001"

def test_webhook(email="test@example.com", amount="5.00", token="test-token-123"):
    """Test Ko-fi webhook endpoint"""
    webhook_data = {
        "message_id": "manual-test-123",
        "kofi_transaction_id": "manual-txn-123", 
        "amount": amount,
        "currency": "USD",
        "from_name": "Manual Test",
        "message": f"{email} - Manual test payment"
    }
    
    data = {
        'data': json.dumps(webhook_data),
        'verification_token': token
    }
    
    print(f"Testing webhook with email: {email}, amount: ${amount}")
    
    try:
        response = requests.post(f"{BASE_URL}/payment/kofi-webhook", data=data)
        print(f"Status: {response.status_code}")
        print(f"Response: {response.text}")
        return response.status_code == 200
    except requests.exceptions.RequestException as e:
        print(f"Error: {e}")
        return False

def test_payment_page():
    """Test payment page accessibility"""
    try:
        response = requests.get(f"{BASE_URL}/payment/extend-account")
        print(f"Payment page status: {response.status_code}")
        return response.status_code in [200, 302]
    except requests.exceptions.RequestException as e:
        print(f"Error accessing payment page: {e}")
        return False

def test_server_running():
    """Check if server is running"""
    try:
        response = requests.get(f"{BASE_URL}/health", timeout=5)
        return response.status_code == 200
    except:
        return False

def main():
    print("=== Ko-fi Payment System Manual Test ===\n")
    
    # Check if server is running
    if not test_server_running():
        print("❌ Server not running on port 5001")
        print("Please start with: uv run dev.py")
        sys.exit(1)
    
    print("✅ Server is running")
    
    # Test payment page access
    print("\n1. Testing payment page access...")
    if test_payment_page():
        print("✅ Payment page accessible")
    else:
        print("❌ Payment page not accessible")
    
    # Test webhook with various scenarios
    print("\n2. Testing webhook scenarios...")
    
    print("\n2a. Valid payment (should fail - user not found):")
    test_webhook("nonexistent@example.com", "5.00", "test-token-123")
    
    print("\n2b. Invalid token:")
    test_webhook("test@example.com", "5.00", "wrong-token")
    
    print("\n2c. Invalid amount:")
    test_webhook("test@example.com", "999.00", "test-token-123")
    
    print("\n=== Test Complete ===")
    print("To test with real users:")
    print("1. Create an invitation and sign up a user")
    print("2. Make the user expired (set expires to past date)")
    print("3. Run: python test_payment_manual.py webhook <user-email>")

if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "webhook":
        email = sys.argv[2] if len(sys.argv) > 2 else "test@example.com"
        test_webhook(email)
    else:
        main()