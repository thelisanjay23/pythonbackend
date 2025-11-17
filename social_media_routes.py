"""
Social Media Integration Routes
Handles webhooks from Facebook, Instagram, Google Ads, WhatsApp
"""
from fastapi import APIRouter, HTTPException, Request, Header
from typing import Optional
import hashlib
import hmac
from datetime import datetime
import os
from dotenv import load_dotenv
from motor.motor_asyncio import AsyncIOMotorClient
from pathlib import Path

# Load environment variables
ROOT_DIR = Path(__file__).parent
load_dotenv(ROOT_DIR / '.env')

# MongoDB connection
mongo_url = os.environ['MONGO_URL']
client = AsyncIOMotorClient(mongo_url)
db = client[os.environ['DB_NAME']]

social_router = APIRouter(prefix="/api/webhooks", tags=["Social Media Integration"])

# ==================== FACEBOOK & INSTAGRAM LEAD ADS ====================

@social_router.get("/facebook")
async def verify_facebook_webhook(
    hub_mode: str = None,
    hub_verify_token: str = None,
    hub_challenge: str = None
):
    """Verify Facebook webhook endpoint"""
    verify_token = os.getenv("FB_VERIFY_TOKEN", "tumble_gym_verify_token_2024")
    
    if hub_mode == "subscribe" and hub_verify_token == verify_token:
        return int(hub_challenge)
    
    raise HTTPException(status_code=403, detail="Verification failed")

@social_router.post("/facebook")
async def handle_facebook_webhook(request: Request):
    """Handle Facebook Lead Ads webhook"""
    try:
        body = await request.json()
        
        # Verify signature
        signature = request.headers.get("x-hub-signature-256", "")
        if not verify_facebook_signature(await request.body(), signature):
            raise HTTPException(status_code=401, detail="Invalid signature")
        
        # Process lead data
        if body.get("object") == "page":
            for entry in body.get("entry", []):
                for change in entry.get("changes", []):
                    if change.get("field") == "leadgen":
                        lead_data = change.get("value", {})
                        await process_facebook_lead(lead_data)
        
        return {"success": True}
    
    except Exception as e:
        print(f"Facebook webhook error: {str(e)}")
        return {"success": False, "error": str(e)}

def verify_facebook_signature(payload: bytes, signature: str) -> bool:
    """Verify Facebook webhook signature"""
    try:
        app_secret = os.getenv("FB_APP_SECRET", "")
        if not app_secret:
            return True  # Skip verification if no secret configured
        
        expected_signature = "sha256=" + hmac.new(
            app_secret.encode(),
            payload,
            hashlib.sha256
        ).hexdigest()
        
        return hmac.compare_digest(expected_signature, signature)
    except:
        return True  # Allow in development

async def process_facebook_lead(lead_data: dict):
    """Process Facebook lead and save to database"""
    try:
        leadgen_id = lead_data.get("leadgen_id")
        
        # Fetch full lead details from Facebook Graph API
        lead_details = await fetch_facebook_lead(leadgen_id)
        
        if not lead_details:
            return
        
        # Extract fields
        name = ""
        phone = ""
        email = ""
        city = ""
        child_age = ""
        
        for field in lead_details.get("field_data", []):
            field_name = field.get("name", "").lower()
            field_value = field.get("values", [""])[0]
            
            if "name" in field_name or "full_name" in field_name:
                name = field_value
            elif "phone" in field_name or "mobile" in field_name:
                phone = field_value.replace("+91", "").replace("-", "").replace(" ", "")[-10:]
            elif "email" in field_name:
                email = field_value
            elif "city" in field_name or "location" in field_name:
                city = field_value
            elif "age" in field_name or "child" in field_name:
                child_age = field_value
        
        # Create lead document
        lead_doc = {
            "id": str(__import__('uuid').uuid4()),
            "name": name,
            "phone": phone,
            "email": email,
            "source": "facebook_lead_ads",
            "status": "new",
            "preferred_centre": city or "Not specified",
            "notes": f"Child Age: {child_age}" if child_age else "",
            "metadata": {
                "leadgen_id": leadgen_id,
                "ad_id": lead_data.get("ad_id"),
                "form_id": lead_data.get("form_id"),
                "platform": "facebook"
            },
            "created_at": datetime.utcnow(),
        }
        
        # Check for duplicates
        existing = await db.leads.find_one({"phone": phone})
        if not existing:
            await db.leads.insert_one(lead_doc)
            print(f"✅ Facebook lead saved: {name} - {phone}")
        else:
            print(f"⚠️ Duplicate lead skipped: {phone}")
    
    except Exception as e:
        print(f"Error processing Facebook lead: {str(e)}")

async def fetch_facebook_lead(leadgen_id: str) -> dict:
    """Fetch lead details from Facebook Graph API"""
    try:
        import httpx
        access_token = os.getenv("FB_PAGE_ACCESS_TOKEN", "")
        
        if not access_token:
            print("⚠️ FB_PAGE_ACCESS_TOKEN not configured")
            return {}
        
        url = f"https://graph.facebook.com/v18.0/{leadgen_id}"
        params = {"access_token": access_token}
        
        async with httpx.AsyncClient() as client:
            response = await client.get(url, params=params)
            return response.json()
    
    except Exception as e:
        print(f"Error fetching Facebook lead: {str(e)}")
        return {}

# ==================== GOOGLE ADS LEAD FORMS ====================

@social_router.post("/google")
async def handle_google_webhook(request: Request):
    """Handle Google Ads Lead Form webhook"""
    try:
        body = await request.json()
        
        # Google sends lead data
        lead_data = body.get("lead", {})
        
        # Extract fields
        name = lead_data.get("name", "")
        phone = lead_data.get("phone_number", "").replace("+91", "")[-10:]
        email = lead_data.get("email", "")
        
        # Additional fields from custom questions
        custom_answers = lead_data.get("custom_question_answers", [])
        city = ""
        child_age = ""
        
        for answer in custom_answers:
            question = answer.get("question", "").lower()
            value = answer.get("answer", "")
            
            if "city" in question or "location" in question:
                city = value
            elif "age" in question or "child" in question:
                child_age = value
        
        # Create lead document
        lead_doc = {
            "id": str(__import__('uuid').uuid4()),
            "name": name,
            "phone": phone,
            "email": email,
            "source": "google_ads",
            "status": "new",
            "preferred_centre": city or "Not specified",
            "notes": f"Child Age: {child_age}" if child_age else "",
            "metadata": {
                "campaign_id": body.get("campaign_id"),
                "ad_group_id": body.get("ad_group_id"),
                "platform": "google_ads"
            },
            "created_at": datetime.utcnow(),
        }
        
        # Check for duplicates
        existing = await db.leads.find_one({"phone": phone})
        if not existing:
            await db.leads.insert_one(lead_doc)
            print(f"✅ Google Ads lead saved: {name} - {phone}")
        else:
            print(f"⚠️ Duplicate lead skipped: {phone}")
        
        return {"success": True}
    
    except Exception as e:
        print(f"Google webhook error: {str(e)}")
        return {"success": False, "error": str(e)}

# ==================== WHATSAPP BUSINESS ====================

@social_router.get("/whatsapp")
async def verify_whatsapp_webhook(
    hub_mode: str = None,
    hub_verify_token: str = None,
    hub_challenge: str = None
):
    """Verify WhatsApp webhook"""
    verify_token = os.getenv("WHATSAPP_VERIFY_TOKEN", "tumble_gym_whatsapp_2024")
    
    if hub_mode == "subscribe" and hub_verify_token == verify_token:
        return int(hub_challenge)
    
    raise HTTPException(status_code=403, detail="Verification failed")

@social_router.post("/whatsapp")
async def handle_whatsapp_webhook(request: Request):
    """Handle WhatsApp Business API webhook"""
    try:
        body = await request.json()
        
        # Process WhatsApp messages
        for entry in body.get("entry", []):
            for change in entry.get("changes", []):
                value = change.get("value", {})
                
                # Handle incoming messages
                for message in value.get("messages", []):
                    await process_whatsapp_message(message, value)
        
        return {"success": True}
    
    except Exception as e:
        print(f"WhatsApp webhook error: {str(e)}")
        return {"success": False, "error": str(e)}

async def process_whatsapp_message(message: dict, value: dict):
    """Process WhatsApp message and create lead if applicable"""
    try:
        message_type = message.get("type")
        from_number = message.get("from", "")
        
        if message_type == "text":
            text = message.get("text", {}).get("body", "").lower()
            
            # Check for lead intent keywords
            keywords = ["interested", "join", "trial", "info", "details", "gymnastics", "fitness"]
            
            if any(keyword in text for keyword in keywords):
                # Create lead from WhatsApp
                lead_doc = {
                    "id": str(__import__('uuid').uuid4()),
                    "name": value.get("contacts", [{}])[0].get("profile", {}).get("name", "WhatsApp User"),
                    "phone": from_number.replace("91", "")[-10:],
                    "email": "",
                    "source": "whatsapp",
                    "status": "new",
                    "preferred_centre": "Not specified",
                    "notes": f"WhatsApp inquiry: {text[:100]}",
                    "metadata": {
                        "platform": "whatsapp",
                        "message_id": message.get("id")
                    },
                    "created_at": datetime.utcnow(),
                }
                
                # Check for duplicates
                existing = await db.leads.find_one({"phone": lead_doc["phone"]})
                if not existing:
                    await db.leads.insert_one(lead_doc)
                    print(f"✅ WhatsApp lead saved: {lead_doc['name']} - {lead_doc['phone']}")
                    
                    # Send auto-reply
                    await send_whatsapp_reply(
                        from_number,
                        "Thank you for your interest in Tumble Gym! 🎉\n\n"
                        "Our team will contact you shortly to discuss enrollment options.\n\n"
                        "Book a FREE trial class: [Link]"
                    )
    
    except Exception as e:
        print(f"Error processing WhatsApp message: {str(e)}")

async def send_whatsapp_reply(to_number: str, message: str):
    """Send WhatsApp reply (requires WhatsApp Business API)"""
    try:
        import httpx
        
        access_token = os.getenv("WHATSAPP_ACCESS_TOKEN", "")
        phone_number_id = os.getenv("WHATSAPP_PHONE_NUMBER_ID", "")
        
        if not access_token or not phone_number_id:
            print("⚠️ WhatsApp credentials not configured")
            return
        
        url = f"https://graph.facebook.com/v18.0/{phone_number_id}/messages"
        headers = {
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json"
        }
        data = {
            "messaging_product": "whatsapp",
            "to": to_number,
            "text": {"body": message}
        }
        
        async with httpx.AsyncClient() as client:
            response = await client.post(url, headers=headers, json=data)
            print(f"✅ WhatsApp reply sent: {response.status_code}")
    
    except Exception as e:
        print(f"Error sending WhatsApp reply: {str(e)}")

# ==================== INSTAGRAM DIRECT MESSAGES ====================

@social_router.post("/instagram")
async def handle_instagram_webhook(request: Request):
    """Handle Instagram DM webhook (uses Facebook webhook)"""
    try:
        body = await request.json()
        
        # Instagram DMs come through Facebook webhook
        for entry in body.get("entry", []):
            messaging = entry.get("messaging", [])
            
            for event in messaging:
                sender_id = event.get("sender", {}).get("id")
                message = event.get("message", {})
                
                if message:
                    await process_instagram_dm(sender_id, message)
        
        return {"success": True}
    
    except Exception as e:
        print(f"Instagram webhook error: {str(e)}")
        return {"success": False, "error": str(e)}

async def process_instagram_dm(sender_id: str, message: dict):
    """Process Instagram DM and create lead"""
    try:
        text = message.get("text", "").lower()
        
        # Check for inquiry intent
        if any(word in text for word in ["interested", "join", "trial", "info"]):
            # Create lead
            lead_doc = {
                "id": str(__import__('uuid').uuid4()),
                "name": f"Instagram User {sender_id[-4:]}",
                "phone": "",  # To be collected
                "email": "",
                "source": "instagram_dm",
                "status": "new",
                "preferred_centre": "Not specified",
                "notes": f"Instagram DM: {text[:100]}",
                "metadata": {
                    "sender_id": sender_id,
                    "platform": "instagram"
                },
                "created_at": datetime.utcnow(),
            }
            
            await db.leads.insert_one(lead_doc)
            print(f"✅ Instagram lead saved: {sender_id}")
    
    except Exception as e:
        print(f"Error processing Instagram DM: {str(e)}")

# ==================== WEBSITE FORM WITH TRACKING ====================

@social_router.post("/website-form")
async def handle_website_form(request: Request):
    """Enhanced website form submission with UTM tracking"""
    try:
        body = await request.json()
        
        # Create lead with full tracking
        lead_doc = {
            "id": str(__import__('uuid').uuid4()),
            "name": body.get("name", ""),
            "phone": body.get("phone", "").replace("+91", "")[-10:],
            "email": body.get("email", ""),
            "source": "website",
            "status": "new",
            "preferred_centre": body.get("city", "Not specified"),
            "notes": body.get("message", ""),
            "metadata": {
                "utm_source": body.get("utm_source", ""),
                "utm_medium": body.get("utm_medium", ""),
                "utm_campaign": body.get("utm_campaign", ""),
                "referrer": body.get("referrer", ""),
                "page": body.get("page_url", ""),
                "platform": "website"
            },
            "created_at": datetime.utcnow(),
        }
        
        # Check for duplicates
        existing = await db.leads.find_one({"phone": lead_doc["phone"]})
        if not existing:
            await db.leads.insert_one(lead_doc)
            print(f"✅ Website lead saved: {lead_doc['name']} - {lead_doc['phone']}")
            return {"success": True, "message": "Thank you! We'll contact you soon."}
        else:
            return {"success": True, "message": "We have your details. Our team will reach out soon!"}
    
    except Exception as e:
        print(f"Website form error: {str(e)}")
        return {"success": False, "error": str(e)}
