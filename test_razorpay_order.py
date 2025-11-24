"""
Quick test to verify Razorpay order creation
"""
import razorpay

# Initialize client
client = razorpay.Client(auth=('rzp_test_MiB7yzxUXfqDJH', 'KwQwvNGACWiZwfTaQtgIbHJK'))

# Test order creation
order_data = {
    "amount": 1250000,  # 12500 * 100 = 1250000 paise
    "currency": "INR",
    "payment_capture": 1,
    "receipt": "pay_d02dbd3f"
}

try:
    print("Creating test order...")
    print(f"Order data: {order_data}")
    order = client.order.create(data=order_data)
    print(f"✓ Order created successfully!")
    print(f"Order ID: {order['id']}")
    print(f"Full order response: {order}")
except Exception as e:
    print(f"✗ Error creating order: {type(e).__name__}")
    print(f"Error message: {str(e)}")
    import traceback
    traceback.print_exc()
