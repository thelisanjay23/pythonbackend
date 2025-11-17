import razorpay
from typing import Dict, Optional
import os
import hmac
import hashlib
from dotenv import load_dotenv

load_dotenv()

# Initialize Razorpay client
RAZORPAY_KEY_ID = os.getenv("RAZORPAY_KEY_ID")
RAZORPAY_KEY_SECRET = os.getenv("RAZORPAY_KEY_SECRET")

if not RAZORPAY_KEY_ID or not RAZORPAY_KEY_SECRET:
    raise ValueError("RAZORPAY_KEY_ID and RAZORPAY_KEY_SECRET must be set in environment variables")

client = razorpay.Client(auth=(RAZORPAY_KEY_ID, RAZORPAY_KEY_SECRET))

# Plan pricing (in INR) - ACCURATE TUMBLE GYM PRICING
PLAN_PRICING = {
    "trial": 0,
    "3_month": 12000,  # Basic 3-month plan
    "6_month": 18000,  # Basic 6-month plan
    "12_month": 32000,  # Basic 12-month plan
    "registration": 2000,  # One-time registration + 18% GST
    
    # 1 Day/Week Programs
    "1day_3month": 9000,
    "1day_6month": 16000,
    "1day_12month": 21000,
    
    # 2 Days/Week Programs
    "2day_3month": 12500,
    "2day_6month": 22500,
    "2day_12month": 32500,
    
    # 3 Days/Week Programs
    "3day_3month": 14000,
    "3day_6month": 24000,
    "3day_12month": 34000,
    
    # Unlimited Classes
    "unlimited_3month": 18000,
    "unlimited_6month": 28000,
    "unlimited_12month": 38000,
    
    # Dance Classes
    "dance_3month": 7500,
    "dance_6month": 12500,
    "dance_12month": 18500,
    
    # Advance Training (per session)
    "advance_level1": 800,
    "advance_level2": 1000,
    "advance_level3": 1200,
    
    # Birthday Parties
    "birthday_12kids": 10000,
    "birthday_15kids": 12500,
    "birthday_20kids": 18000,
}

GST_RATE = 0.18  # 18% GST

def calculate_amount(plan_type: str, coupon_discount: float = 0) -> Dict[str, float]:
    """Calculate amount with GST"""
    base_amount = PLAN_PRICING.get(plan_type, 0)
    discounted_amount = base_amount - coupon_discount
    tax_amount = discounted_amount * GST_RATE
    total_amount = discounted_amount + tax_amount
    
    return {
        "base_amount": base_amount,
        "discount": coupon_discount,
        "amount": discounted_amount,
        "tax_amount": tax_amount,
        "total_amount": total_amount
    }

def create_order(amount: float, currency: str = "INR", receipt: Optional[str] = None) -> Dict:
    """Create Razorpay order"""
    # Amount should be in paise (multiply by 100)
    amount_in_paise = int(amount * 100)
    
    order_data = {
        "amount": amount_in_paise,
        "currency": currency,
        "payment_capture": 1  # Auto capture
    }
    
    if receipt:
        order_data["receipt"] = receipt
    
    try:
        order = client.order.create(data=order_data)
        return {
            "success": True,
            "order_id": order["id"],
            "amount": amount,
            "currency": currency
        }
    except Exception as e:
        return {
            "success": False,
            "error": str(e)
        }

def verify_payment_signature(order_id: str, payment_id: str, signature: str) -> bool:
    """Verify Razorpay payment signature"""
    try:
        params_dict = {
            'razorpay_order_id': order_id,
            'razorpay_payment_id': payment_id,
            'razorpay_signature': signature
        }
        client.utility.verify_payment_signature(params_dict)
        return True
    except:
        return False

def create_refund(payment_id: str, amount: Optional[float] = None) -> Dict:
    """Create refund for a payment"""
    try:
        refund_data = {"payment_id": payment_id}
        if amount:
            refund_data["amount"] = int(amount * 100)  # Convert to paise
        
        refund = client.payment.refund(payment_id, refund_data)
        return {
            "success": True,
            "refund_id": refund["id"],
            "amount": refund["amount"] / 100,
            "status": refund["status"]
        }
    except Exception as e:
        return {
            "success": False,
            "error": str(e)
        }

def fetch_payment(payment_id: str) -> Dict:
    """Fetch payment details"""
    try:
        payment = client.payment.fetch(payment_id)
        return {
            "success": True,
            "payment": payment
        }
    except Exception as e:
        return {
            "success": False,
            "error": str(e)
        }

def generate_gst_invoice_data(payment: Dict, enrollment: Dict, child: Dict, location: Dict) -> Dict:
    """Generate GST invoice data"""
    return {
        "invoice_number": payment.get("invoice_number"),
        "invoice_date": payment.get("created_at"),
        "customer_name": child.get("name"),
        "customer_phone": "",  # Add from parent
        "customer_gstin": payment.get("gstin"),
        "supplier_name": "Tumble Gym India Pvt Ltd",
        "supplier_address": location.get("address"),
        "supplier_gstin": location.get("gstin"),
        "items": [
            {
                "description": f"Tumble Gym Enrollment - {enrollment.get('plan_type')}",
                "hsn_sac": "999293",  # Fitness services SAC code
                "quantity": 1,
                "rate": payment.get("amount"),
                "taxable_value": payment.get("amount"),
                "cgst_rate": 9.0,
                "cgst_amount": payment.get("tax_amount") / 2,
                "sgst_rate": 9.0,
                "sgst_amount": payment.get("tax_amount") / 2,
                "total": payment.get("total_amount")
            }
        ],
        "total_taxable": payment.get("amount"),
        "total_cgst": payment.get("tax_amount") / 2,
        "total_sgst": payment.get("tax_amount") / 2,
        "grand_total": payment.get("total_amount"),
        "amount_in_words": number_to_words(int(payment.get("total_amount")))
    }

def number_to_words(num: int) -> str:
    """Convert number to words for invoice"""
    # Simple implementation - can be enhanced
    ones = ["", "One", "Two", "Three", "Four", "Five", "Six", "Seven", "Eight", "Nine"]
    teens = ["Ten", "Eleven", "Twelve", "Thirteen", "Fourteen", "Fifteen", "Sixteen", "Seventeen", "Eighteen", "Nineteen"]
    tens = ["", "", "Twenty", "Thirty", "Forty", "Fifty", "Sixty", "Seventy", "Eighty", "Ninety"]
    
    if num == 0:
        return "Zero Rupees Only"
    
    if num < 10:
        return f"{ones[num]} Rupees Only"
    elif num < 20:
        return f"{teens[num-10]} Rupees Only"
    elif num < 100:
        return f"{tens[num//10]} {ones[num%10]} Rupees Only".strip()
    elif num < 1000:
        return f"{ones[num//100]} Hundred {number_to_words(num%100)}".strip()
    elif num < 100000:
        return f"{number_to_words(num//1000)} Thousand {number_to_words(num%1000)}".strip()
    else:
        return f"{number_to_words(num//100000)} Lakh {number_to_words(num%100000)}".strip()
