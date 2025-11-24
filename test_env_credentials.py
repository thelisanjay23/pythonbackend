"""
Test if .env credentials are loaded correctly
"""
import os
from dotenv import load_dotenv
from pathlib import Path

# Load .env
ROOT_DIR = Path(__file__).parent
load_dotenv(ROOT_DIR / '.env')

key_id = os.getenv("RAZORPAY_KEY_ID")
key_secret = os.getenv("RAZORPAY_KEY_SECRET")

print("=" * 60)
print("Environment Variables Test")
print("=" * 60)
print(f"RAZORPAY_KEY_ID: {key_id}")
print(f"RAZORPAY_KEY_SECRET: {key_secret}")
print(f"Key ID Length: {len(key_id) if key_id else 0}")
print(f"Key Secret Length: {len(key_secret) if key_secret else 0}")
print("=" * 60)

# Test with these credentials
if key_id and key_secret:
    print("\nTesting Razorpay client with loaded credentials...")
    try:
        import razorpay
        client = razorpay.Client(auth=(key_id, key_secret))
        print("✓ Client created successfully")
        
        # Try creating a test order
        order_data = {
            "amount": 100,  # 1 rupee in paise
            "currency": "INR",
            "payment_capture": 1
        }
        print(f"\nAttempting to create test order...")
        order = client.order.create(data=order_data)
        print(f"✓ Order created: {order['id']}")
    except Exception as e:
        print(f"✗ Error: {type(e).__name__}: {str(e)}")
