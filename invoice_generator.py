"""
Invoice Generator for Tumble Time Pvt Ltd
Generates professional invoices with GST billing
"""

from datetime import datetime, timedelta
from typing import Dict, Any

COMPANY_DETAILS = {
    "name": "Tumble Time Pvt Ltd",
    "address": "123 Fitness Plaza, MG Road",
    "city": "Bangalore, Karnataka - 560001",
    "gstin": "29AABCT1234F1Z5",
    "pan": "AABCT1234F",
    "phone": "+91 7019271281",
    "email": "billing@tumbletime.in",
    "website": "www.tumblegym.in",
}

TERMS_AND_CONDITIONS = [
    "Payment is non-refundable once enrollment is confirmed.",
    "Classes can be paused for a maximum of 30 days per enrollment period with 7 days prior notice.",
    "Paused classes will extend the enrollment end date by the pause duration.",
    "Resume requires 3 days advance notice to the center coordinator.",
    "Missed classes without prior intimation cannot be made up or refunded.",
    "Membership is non-transferable to another individual.",
    "Management reserves the right to reschedule or cancel classes with prior notice.",
    "Members must follow safety guidelines and center rules at all times.",
    "Medical fitness certificate may be required for certain programs.",
    "This invoice is computer generated and does not require a signature.",
]

PAUSE_RESUME_POLICY = {
    "pause_max_days": 30,
    "pause_notice_days": 7,
    "resume_notice_days": 3,
    "pause_allowed_times": 2,  # Maximum times pause allowed per enrollment
}

def calculate_gst(base_amount: float, gst_rate: float = 18.0) -> Dict[str, float]:
    """Calculate GST components"""
    cgst_rate = gst_rate / 2
    sgst_rate = gst_rate / 2
    
    cgst_amount = round((base_amount * cgst_rate) / 100, 2)
    sgst_amount = round((base_amount * sgst_rate) / 100, 2)
    total_gst = cgst_amount + sgst_amount
    total_amount = base_amount + total_gst
    
    return {
        "base_amount": base_amount,
        "cgst_rate": cgst_rate,
        "cgst_amount": cgst_amount,
        "sgst_rate": sgst_rate,
        "sgst_amount": sgst_amount,
        "total_gst": total_gst,
        "total_amount": round(total_amount, 2),
    }

def generate_invoice_data(
    invoice_number: str,
    customer_name: str,
    customer_phone: str,
    customer_email: str,
    customer_address: str,
    child_name: str,
    program_name: str,
    plan_type: str,
    base_amount: float,
    start_date: datetime,
    end_date: datetime,
    center_name: str,
    payment_id: str,
    payment_method: str = "Online",
) -> Dict[str, Any]:
    """Generate complete invoice data"""
    
    # Calculate duration and number of classes
    duration_days = (end_date - start_date).days
    duration_months = round(duration_days / 30)
    
    # Parse plan_type to get frequency (e.g., "2day_6month" -> 2 days/week)
    frequency = plan_type.split('_')[0] if '_' in plan_type else '2day'
    classes_per_week = int(frequency.replace('day', '')) if frequency != 'unlimited' else 'Unlimited'
    
    # Calculate approximate total classes
    if classes_per_week == 'Unlimited':
        total_classes = "Unlimited"
    else:
        weeks = duration_days / 7
        total_classes = int(classes_per_week * weeks)
    
    # Calculate GST
    gst_details = calculate_gst(base_amount)
    
    # Generate invoice data
    invoice_data = {
        "invoice_number": invoice_number,
        "invoice_date": datetime.now().strftime("%d/%m/%Y"),
        "due_date": datetime.now().strftime("%d/%m/%Y"),  # Paid invoice
        "status": "PAID",
        
        # Company details
        "company": COMPANY_DETAILS,
        
        # Customer details
        "customer": {
            "name": customer_name,
            "phone": customer_phone,
            "email": customer_email,
            "address": customer_address,
        },
        
        # Enrollment details
        "enrollment": {
            "child_name": child_name,
            "program_name": program_name,
            "plan_type": plan_type,
            "center_name": center_name,
            "start_date": start_date.strftime("%d/%m/%Y"),
            "end_date": end_date.strftime("%d/%m/%Y"),
            "duration_months": duration_months,
            "classes_per_week": classes_per_week,
            "total_classes": total_classes,
        },
        
        # Financial details
        "financial": {
            "base_amount": base_amount,
            "cgst_rate": gst_details["cgst_rate"],
            "cgst_amount": gst_details["cgst_amount"],
            "sgst_rate": gst_details["sgst_rate"],
            "sgst_amount": gst_details["sgst_amount"],
            "total_gst": gst_details["total_gst"],
            "total_amount": gst_details["total_amount"],
            "amount_in_words": number_to_words(gst_details["total_amount"]),
        },
        
        # Payment details
        "payment": {
            "payment_id": payment_id,
            "payment_method": payment_method,
            "payment_date": datetime.now().strftime("%d/%m/%Y %H:%M:%S"),
        },
        
        # Policies
        "pause_resume_policy": PAUSE_RESUME_POLICY,
        "terms_and_conditions": TERMS_AND_CONDITIONS,
    }
    
    return invoice_data

def number_to_words(num: float) -> str:
    """Convert number to words (Indian numbering system)"""
    ones = ["", "One", "Two", "Three", "Four", "Five", "Six", "Seven", "Eight", "Nine"]
    tens = ["", "", "Twenty", "Thirty", "Forty", "Fifty", "Sixty", "Seventy", "Eighty", "Ninety"]
    teens = ["Ten", "Eleven", "Twelve", "Thirteen", "Fourteen", "Fifteen", 
             "Sixteen", "Seventeen", "Eighteen", "Nineteen"]
    
    def convert_below_thousand(n: int) -> str:
        if n == 0:
            return ""
        elif n < 10:
            return ones[n]
        elif n < 20:
            return teens[n - 10]
        elif n < 100:
            return tens[n // 10] + (" " + ones[n % 10] if n % 10 != 0 else "")
        else:
            return ones[n // 100] + " Hundred" + (" " + convert_below_thousand(n % 100) if n % 100 != 0 else "")
    
    # Split into rupees and paise
    rupees = int(num)
    paise = int(round((num - rupees) * 100))
    
    if rupees == 0:
        result = "Zero Rupees"
    else:
        # Indian numbering: Crores, Lakhs, Thousands, Hundreds
        crores = rupees // 10000000
        lakhs = (rupees % 10000000) // 100000
        thousands = (rupees % 100000) // 1000
        hundreds = rupees % 1000
        
        result_parts = []
        if crores > 0:
            result_parts.append(convert_below_thousand(crores) + " Crore")
        if lakhs > 0:
            result_parts.append(convert_below_thousand(lakhs) + " Lakh")
        if thousands > 0:
            result_parts.append(convert_below_thousand(thousands) + " Thousand")
        if hundreds > 0:
            result_parts.append(convert_below_thousand(hundreds))
        
        result = " ".join(result_parts) + " Rupees"
    
    if paise > 0:
        result += " and " + convert_below_thousand(paise) + " Paise"
    
    result += " Only"
    return result
