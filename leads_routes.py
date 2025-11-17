"""
Lead Capture & CRM Integration System for Tumble Gym
Multi-source lead intake with Zoho CRM / LeadSquared adapter
"""

from fastapi import APIRouter, HTTPException, Depends, BackgroundTasks, Request
from motor.motor_asyncio import AsyncIOMotorClient
from dotenv import load_dotenv
from pathlib import Path
import os
from datetime import datetime, timedelta
from typing import List, Optional, Dict, Any
import uuid
import re
import hashlib
import asyncio

from models import *
from auth import get_current_user

ROOT_DIR = Path(__file__).parent
load_dotenv(ROOT_DIR / '.env')

mongo_url = os.environ['MONGO_URL']
client = AsyncIOMotorClient(mongo_url)
db = client[os.environ['DB_NAME']]

leads_router = APIRouter(prefix="/api/leads", tags=["Lead Management"])
webhooks_router = APIRouter(prefix="/api/webhooks", tags=["Webhooks"])

# ==================== LEAD VALIDATION ====================

def validate_phone(phone: str) -> bool:
    """Validate Indian mobile number format"""
    pattern = r'^[6-9]\d{9}$'
    return bool(re.match(pattern, phone))

def validate_email(email: str) -> bool:
    """Validate email format"""
    pattern = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
    return bool(re.match(pattern, email))

async def check_duplicate_lead(phone: str, centre: str) -> Optional[dict]:
    """Check if lead exists within 30 days for same centre"""
    thirty_days_ago = datetime.utcnow() - timedelta(days=30)
    existing = await db.leads.find_one({
        "phone": phone,
        "preferred_centre": centre,
        "created_at": {"$gte": thirty_days_ago}
    })
    return existing

async def generate_lead_score(lead_data: dict) -> int:
    """Calculate lead score based on various factors"""
    score = 50  # Base score
    
    # Source scoring
    source_scores = {
        "referral": 30,
        "walkin": 25,
        "website": 20,
        "whatsapp": 15,
        "fb_lead_ads": 10,
        "google_ads": 10,
        "event": 15
    }
    score += source_scores.get(lead_data.get("source"), 0)
    
    # Urgency indicators
    if lead_data.get("notes") and any(word in lead_data["notes"].lower() for word in ["urgent", "immediate", "today"]):
        score += 20
    
    # Consents
    consents = lead_data.get("consents", {})
    if consents.get("whatsapp"):
        score += 10
    if consents.get("callsms"):
        score += 5
    
    # Preferred slot provided
    if lead_data.get("preferred_slot"):
        score += 10
    
    # Email provided
    if lead_data.get("email"):
        score += 5
    
    return min(score, 100)

# ==================== LEAD CREATION API ====================

@leads_router.post("")
async def create_lead(
    lead_data: dict,
    background_tasks: BackgroundTasks,
    request: Request,
    current_user: Optional[dict] = None
):
    """
    Create new lead from any source
    Supports: Website, App, WhatsApp, Walk-in, Referral, Event
    """
    
    # Validate required fields
    if not lead_data.get("name"):
        raise HTTPException(status_code=400, detail="Name is required")
    if not lead_data.get("phone"):
        raise HTTPException(status_code=400, detail="Phone is required")
    if not validate_phone(lead_data["phone"]):
        raise HTTPException(status_code=400, detail="Invalid phone number format")
    if not lead_data.get("program"):
        raise HTTPException(status_code=400, detail="Program is required")
    
    # Validate email if provided
    if lead_data.get("email") and not validate_email(lead_data["email"]):
        raise HTTPException(status_code=400, detail="Invalid email format")
    
    # Check for duplicates
    duplicate = await check_duplicate_lead(
        lead_data["phone"],
        lead_data.get("preferred_centre", "")
    )
    
    if duplicate:
        # Update existing lead instead
        await db.leads.update_one(
            {"id": duplicate["id"]},
            {"$set": {
                "updated_at": datetime.utcnow(),
                "notes": f"{duplicate.get('notes', '')} | Updated: {lead_data.get('notes', '')}"
            }}
        )
        return {
            "success": True,
            "lead_id": duplicate["id"],
            "message": "Existing lead updated",
            "duplicate": True
        }
    
    # Calculate lead score
    score = await generate_lead_score(lead_data)
    
    # Create new lead
    lead = {
        "id": str(uuid.uuid4()),
        "name": lead_data["name"],
        "phone": lead_data["phone"],
        "email": lead_data.get("email"),
        "program": lead_data["program"],
        "member_type": lead_data.get("member_type", "child"),
        "child_age": lead_data.get("child_age"),
        "preferred_centre": lead_data.get("preferred_centre"),
        "preferred_slot": lead_data.get("preferred_slot"),
        "utm_source": lead_data.get("utm_source"),
        "utm_medium": lead_data.get("utm_medium"),
        "utm_campaign": lead_data.get("utm_campaign"),
        "utm_content": lead_data.get("utm_content"),
        "utm_term": lead_data.get("utm_term"),
        "source": lead_data.get("source", "website"),
        "referral_code": lead_data.get("referral_code"),
        "status": "new",
        "score": score,
        "owner": current_user.get("sub") if current_user else None,
        "consents": {
            "marketing": lead_data.get("consents", {}).get("marketing", False),
            "whatsapp": lead_data.get("consents", {}).get("whatsapp", False),
            "callsms": lead_data.get("consents", {}).get("callsms", False),
            "timestamp": datetime.utcnow(),
            "ip": request.client.host if request.client else None
        },
        "notes": lead_data.get("notes", ""),
        "timeline": [{
            "event": "created",
            "timestamp": datetime.utcnow(),
            "details": f"Lead created from {lead_data.get('source', 'website')}"
        }],
        "created_at": datetime.utcnow(),
        "updated_at": datetime.utcnow()
    }
    
    await db.leads.insert_one(lead)
    
    # Background tasks
    background_tasks.add_task(sync_to_crm, lead)
    background_tasks.add_task(send_welcome_message, lead)
    background_tasks.add_task(auto_assign_lead, lead)
    
    return {
        "success": True,
        "lead_id": lead["id"],
        "score": score,
        "message": "Lead created successfully"
    }

@leads_router.post("/bulk")
async def create_bulk_leads(
    leads_data: List[dict],
    background_tasks: BackgroundTasks
):
    """
    Bulk lead creation for ad sync (Facebook, Google)
    Supports idempotency
    """
    created = []
    duplicates = []
    errors = []
    
    for lead_data in leads_data:
        try:
            # Check duplicate
            if await check_duplicate_lead(lead_data.get("phone"), lead_data.get("preferred_centre", "")):
                duplicates.append(lead_data.get("phone"))
                continue
            
            score = await generate_lead_score(lead_data)
            
            lead = {
                "id": str(uuid.uuid4()),
                "name": lead_data["name"],
                "phone": lead_data["phone"],
                "email": lead_data.get("email"),
                "program": lead_data.get("program", "tumble_gym"),
                "preferred_centre": lead_data.get("preferred_centre"),
                "source": lead_data.get("source", "fb_lead_ads"),
                "status": "new",
                "score": score,
                "consents": lead_data.get("consents", {}),
                "timeline": [{"event": "created", "timestamp": datetime.utcnow()}],
                "created_at": datetime.utcnow(),
                "updated_at": datetime.utcnow()
            }
            
            await db.leads.insert_one(lead)
            created.append(lead["id"])
            
            background_tasks.add_task(sync_to_crm, lead)
            
        except Exception as e:
            errors.append({"phone": lead_data.get("phone"), "error": str(e)})
    
    return {
        "success": True,
        "created": len(created),
        "duplicates": len(duplicates),
        "errors": len(errors),
        "details": {"created": created, "duplicates": duplicates, "errors": errors}
    }

# ==================== LEAD RETRIEVAL & MANAGEMENT ====================

@leads_router.get("")
async def get_leads(
    centre: Optional[str] = None,
    status: Optional[str] = None,
    program: Optional[str] = None,
    source: Optional[str] = None,
    owner: Optional[str] = None,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    score_min: Optional[int] = None,
    page: int = 1,
    limit: int = 50,
    current_user: dict = Depends(get_current_user)
):
    """Get leads with advanced filtering"""
    
    query = {}
    
    if centre:
        query["preferred_centre"] = centre
    if status:
        query["status"] = status
    if program:
        query["program"] = program
    if source:
        query["source"] = source
    if owner:
        query["owner"] = owner
    if score_min:
        query["score"] = {"$gte": score_min}
    
    if date_from and date_to:
        query["created_at"] = {
            "$gte": datetime.fromisoformat(date_from),
            "$lte": datetime.fromisoformat(date_to)
        }
    
    # Role-based filtering
    if current_user.get("role") == "manager":
        user = await db.users.find_one({"id": current_user["sub"]})
        if user and user.get("assigned_locations"):
            query["preferred_centre"] = {"$in": user["assigned_locations"]}
    
    skip = (page - 1) * limit
    leads = await db.leads.find(query).sort("created_at", -1).skip(skip).limit(limit).to_list(limit)
    total = await db.leads.count_documents(query)
    
    # Enrich with owner details
    for lead in leads:
        if lead.get("owner"):
            owner_user = await db.users.find_one({"id": lead["owner"]})
            if owner_user:
                lead["owner_name"] = owner_user.get("name")
    
    return {
        "leads": leads,
        "total": total,
        "page": page,
        "pages": (total + limit - 1) // limit
    }

@leads_router.get("/{lead_id}")
async def get_lead_details(
    lead_id: str,
    current_user: dict = Depends(get_current_user)
):
    """Get detailed lead information"""
    lead = await db.leads.find_one({"id": lead_id})
    if not lead:
        raise HTTPException(status_code=404, detail="Lead not found")
    
    # Get trial bookings
    trials = await db.trial_bookings.find({"lead_id": lead_id}).to_list(10)
    lead["trial_bookings"] = trials
    
    # Get CRM sync status
    crm_sync = await db.crm_sync_log.find({"lead_id": lead_id}).sort("synced_at", -1).limit(5).to_list(5)
    lead["crm_sync_history"] = crm_sync
    
    return lead

@leads_router.patch("/{lead_id}")
async def update_lead(
    lead_id: str,
    updates: dict,
    background_tasks: BackgroundTasks,
    current_user: dict = Depends(get_current_user)
):
    """Update lead fields"""
    lead = await db.leads.find_one({"id": lead_id})
    if not lead:
        raise HTTPException(status_code=404, detail="Lead not found")
    
    # Add to timeline
    if "status" in updates and updates["status"] != lead.get("status"):
        timeline_event = {
            "event": "status_change",
            "timestamp": datetime.utcnow(),
            "from": lead.get("status"),
            "to": updates["status"],
            "by": current_user["sub"]
        }
        await db.leads.update_one(
            {"id": lead_id},
            {"$push": {"timeline": timeline_event}}
        )
    
    updates["updated_at"] = datetime.utcnow()
    
    await db.leads.update_one(
        {"id": lead_id},
        {"$set": updates}
    )
    
    # Sync to CRM
    background_tasks.add_task(sync_to_crm, {**lead, **updates})
    
    return {"success": True}

@leads_router.post("/{lead_id}/assign")
async def assign_lead(
    lead_id: str,
    owner_id: str,
    current_user: dict = Depends(get_current_user)
):
    """Assign lead to owner"""
    if current_user.get("role") not in ["admin", "manager"]:
        raise HTTPException(status_code=403, detail="Not authorized")
    
    # Verify owner exists
    owner = await db.users.find_one({"id": owner_id})
    if not owner:
        raise HTTPException(status_code=404, detail="Owner not found")
    
    await db.leads.update_one(
        {"id": lead_id},
        {"$set": {
            "owner": owner_id,
            "updated_at": datetime.utcnow()
        }, "$push": {
            "timeline": {
                "event": "assigned",
                "timestamp": datetime.utcnow(),
                "to": owner_id,
                "by": current_user["sub"]
            }
        }}
    )
    
    return {"success": True, "assigned_to": owner["name"]}

@leads_router.post("/{lead_id}/events")
async def add_lead_event(
    lead_id: str,
    event_data: dict,
    current_user: dict = Depends(get_current_user)
):
    """Add timeline event to lead"""
    event = {
        "event": event_data["event"],
        "timestamp": datetime.utcnow(),
        "details": event_data.get("details"),
        "by": current_user.get("sub")
    }
    
    await db.leads.update_one(
        {"id": lead_id},
        {"$push": {"timeline": event}}
    )
    
    return {"success": True}

# ==================== TRIAL BOOKING ====================

@leads_router.post("/trial-bookings")
async def create_trial_booking(
    booking_data: dict,
    background_tasks: BackgroundTasks,
    current_user: Optional[dict] = None
):
    """Create trial booking linked to lead"""
    
    # Create or update lead if phone provided
    lead_id = booking_data.get("lead_id")
    
    if not lead_id and booking_data.get("phone"):
        # Try to find existing lead
        lead = await db.leads.find_one({"phone": booking_data["phone"]})
        if lead:
            lead_id = lead["id"]
        else:
            # Create new lead
            lead_response = await create_lead({
                "name": booking_data["name"],
                "phone": booking_data["phone"],
                "email": booking_data.get("email"),
                "program": booking_data["program"],
                "preferred_centre": booking_data["centre"],
                "source": "trial_booking",
                "consents": booking_data.get("consents", {})
            }, background_tasks, None, current_user)
            lead_id = lead_response["lead_id"]
    
    # Create trial booking
    trial = {
        "id": str(uuid.uuid4()),
        "lead_id": lead_id,
        "name": booking_data["name"],
        "phone": booking_data["phone"],
        "programme": booking_data["program"],
        "centre": booking_data["centre"],
        "trial_date": datetime.fromisoformat(booking_data["trial_date"]) if isinstance(booking_data.get("trial_date"), str) else booking_data.get("trial_date"),
        "slot": booking_data.get("slot"),
        "status": "confirmed",
        "created_at": datetime.utcnow()
    }
    
    await db.trial_bookings.insert_one(trial)
    
    # Update lead status
    if lead_id:
        await db.leads.update_one(
            {"id": lead_id},
            {"$set": {"status": "trial_booked"}, "$push": {
                "timeline": {
                    "event": "trial_booked",
                    "timestamp": datetime.utcnow(),
                    "details": f"Trial scheduled for {booking_data.get('trial_date')}"
                }
            }}
        )
    
    return {"success": True, "trial_id": trial["id"], "lead_id": lead_id}

# ==================== WEBHOOKS ====================

@webhooks_router.post("/facebook")
async def facebook_webhook(
    request: Request,
    background_tasks: BackgroundTasks
):
    """Handle Facebook Lead Ads webhook"""
    data = await request.json()
    
    # Verify Facebook signature (implement in production)
    # ...
    
    if data.get("entry"):
        for entry in data["entry"]:
            for change in entry.get("changes", []):
                if change.get("field") == "leadgen":
                    leadgen_id = change["value"]["leadgen_id"]
                    
                    # Fetch lead data from Facebook Graph API
                    # (Implement Facebook SDK call)
                    
                    lead_data = {
                        "name": "FB Lead",  # Parse from API
                        "phone": "9999999999",  # Parse from API
                        "program": "tumble_gym",
                        "source": "fb_lead_ads",
                        "utm_source": "facebook",
                        "utm_medium": "cpc"
                    }
                    
                    background_tasks.add_task(create_lead, lead_data, background_tasks, request, None)
    
    return {"success": True}

@webhooks_router.post("/google")
async def google_webhook(
    request: Request,
    background_tasks: BackgroundTasks
):
    """Handle Google Ads Lead Form webhook"""
    data = await request.json()
    
    # Parse Google lead form data
    lead_data = {
        "name": data.get("name"),
        "phone": data.get("phone"),
        "email": data.get("email"),
        "program": data.get("program", "tumble_gym"),
        "source": "google_ads",
        "utm_source": "google",
        "utm_medium": "cpc",
        "utm_campaign": data.get("campaign_id")
    }
    
    background_tasks.add_task(create_lead, lead_data, background_tasks, request, None)
    
    return {"success": True}

@webhooks_router.post("/whatsapp")
async def whatsapp_webhook(
    request: Request,
    background_tasks: BackgroundTasks
):
    """Handle WhatsApp Business API webhook"""
    data = await request.json()
    
    # Parse WhatsApp message
    if data.get("messages"):
        for message in data["messages"]:
            phone = message.get("from")
            text = message.get("text", {}).get("body", "")
            
            # Check if lead exists
            lead = await db.leads.find_one({"phone": phone})
            
            if lead:
                # Update timeline
                await db.leads.update_one(
                    {"id": lead["id"]},
                    {"$push": {
                        "timeline": {
                            "event": "whatsapp_message",
                            "timestamp": datetime.utcnow(),
                            "message": text
                        }
                    }}
                )
            else:
                # Create new lead from WhatsApp
                lead_data = {
                    "name": message.get("profile", {}).get("name", "WhatsApp Lead"),
                    "phone": phone,
                    "source": "whatsapp",
                    "consents": {"whatsapp": True},
                    "notes": f"Initial message: {text}"
                }
                background_tasks.add_task(create_lead, lead_data, background_tasks, request, None)
    
    return {"success": True}

@webhooks_router.post("/crm")
async def crm_webhook(
    request: Request
):
    """Handle inbound CRM updates (Zoho/LeadSquared)"""
    data = await request.json()
    
    # Parse CRM data
    crm_lead_id = data.get("id")
    status = data.get("status")
    
    # Find lead by CRM ID
    lead = await db.leads.find_one({"crm_lead_id": crm_lead_id})
    
    if lead:
        await db.leads.update_one(
            {"id": lead["id"]},
            {"$set": {
                "status": status,
                "updated_at": datetime.utcnow()
            }}
        )
    
    return {"success": True}

# ==================== BACKGROUND TASKS ====================

async def sync_to_crm(lead: dict):
    """Sync lead to CRM (Zoho/LeadSquared)"""
    # Use CRM adapter (implement based on choice)
    # ...
    
    # Log sync
    await db.crm_sync_log.insert_one({
        "lead_id": lead["id"],
        "crm_system": "zoho",  # or "leadsquared"
        "status": "success",
        "synced_at": datetime.utcnow()
    })

async def send_welcome_message(lead: dict):
    """Send welcome message via WhatsApp/SMS"""
    if lead.get("consents", {}).get("whatsapp"):
        # Send WhatsApp template
        # (Implement Gupshup/Interakt API)
        pass

async def auto_assign_lead(lead: dict):
    """Auto-assign lead based on rules"""
    # Round-robin or rule-based assignment
    centre = lead.get("preferred_centre")
    
    if centre:
        # Find available owner for this centre
        owners = await db.users.find({
            "role": {"$in": ["manager", "franchise"]},
            "assigned_locations": centre,
            "active": True
        }).to_list(10)
        
        if owners:
            # Simple round-robin
            owner = owners[0]
            await db.leads.update_one(
                {"id": lead["id"]},
                {"$set": {"owner": owner["id"]}}
            )

# ==================== REPORTING ====================

@leads_router.get("/analytics/summary")
async def get_lead_analytics(
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    centre: Optional[str] = None,
    current_user: dict = Depends(get_current_user)
):
    """Get lead analytics summary"""
    
    query = {}
    if date_from and date_to:
        query["created_at"] = {
            "$gte": datetime.fromisoformat(date_from),
            "$lte": datetime.fromisoformat(date_to)
        }
    if centre:
        query["preferred_centre"] = centre
    
    # Total leads
    total = await db.leads.count_documents(query)
    
    # By status
    statuses = {}
    for status in ["new", "contacted", "trial_booked", "enrolled", "lost"]:
        count = await db.leads.count_documents({**query, "status": status})
        statuses[status] = count
    
    # By source
    sources = {}
    for source in ["website", "whatsapp", "fb_lead_ads", "google_ads", "walkin", "referral", "event"]:
        count = await db.leads.count_documents({**query, "source": source})
        sources[source] = count
    
    # Conversion rate
    enrolled = statuses.get("enrolled", 0)
    conversion_rate = (enrolled / total * 100) if total > 0 else 0
    
    # Average score
    leads = await db.leads.find(query).to_list(10000)
    avg_score = sum(l.get("score", 0) for l in leads) / len(leads) if leads else 0
    
    return {
        "total_leads": total,
        "by_status": statuses,
        "by_source": sources,
        "conversion_rate": round(conversion_rate, 2),
        "average_score": round(avg_score, 2),
        "enrolled": enrolled
    }
