"""
Admin Dashboard Routes for Tumble Gym
Comprehensive admin endpoints for managing operations across all centers
"""

from fastapi import APIRouter, HTTPException, Depends, Query
from fastapi.encoders import jsonable_encoder
from motor.motor_asyncio import AsyncIOMotorClient
from dotenv import load_dotenv
from pathlib import Path
import os
from datetime import datetime, timedelta, date
from typing import List, Optional, Dict, Any
from bson import ObjectId
import logging

# Import models and utilities
from models import *
from auth import get_current_user

ROOT_DIR = Path(__file__).parent
load_dotenv(ROOT_DIR / '.env')

# MongoDB connection
mongo_url = os.environ['MONGO_URL']
client = AsyncIOMotorClient(mongo_url)
db = client[os.environ['DB_NAME']]

# Create admin router
admin_router = APIRouter(prefix="/api/admin", tags=["Admin Dashboard"])

logger = logging.getLogger(__name__)

# Helper function to serialize MongoDB documents
def serialize_doc(doc):
    """Convert MongoDB document for JSON serialization"""
    if isinstance(doc, dict):
        if "_id" in doc:
            doc["_id"] = str(doc["_id"])
        for key, value in doc.items():
            if isinstance(value, ObjectId):
                doc[key] = str(value)
            elif isinstance(value, dict):
                doc[key] = serialize_doc(value)
            elif isinstance(value, list):
                doc[key] = [serialize_doc(item) if isinstance(item, dict) else item for item in value]
    return doc

# ==================== 1. ENHANCED HOME DASHBOARD ====================

@admin_router.get("/dashboard/enhanced")
async def get_enhanced_dashboard(
    centre_id: Optional[str] = None,
    brand: Optional[str] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    current_user: dict = Depends(get_current_user)
):
    """
    Enhanced dashboard with live widgets and filters
    Supports filtering by centre, brand, and date range
    """
    if current_user.get("role") not in ["admin", "franchise"]:
        raise HTTPException(status_code=403, detail="Not authorized")
    
    # Build query filters
    query_filter = {}
    if centre_id:
        query_filter["location_id"] = centre_id
    if brand:
        query_filter["brand"] = brand
    
    # Date filters
    today = datetime.utcnow().replace(hour=0, minute=0, second=0)
    week_start = today - timedelta(days=today.weekday())
    month_start = today.replace(day=1)
    
    # Enrollments statistics
    total_enrollments = await db.enrollments.count_documents({})
    active_enrollments = await db.enrollments.count_documents({"status": "active"})
    paused_enrollments = await db.enrollments.count_documents({"status": "paused"})
    expired_enrollments = await db.enrollments.count_documents({"status": "expired"})
    
    # Revenue calculations
    revenue_today = await calculate_revenue(today, today + timedelta(days=1), centre_id)
    revenue_this_week = await calculate_revenue(week_start, today + timedelta(days=1), centre_id)
    revenue_this_month = await calculate_revenue(month_start, today + timedelta(days=1), centre_id)
    revenue_by_centre = await get_revenue_by_centre()
    
    # Attendance statistics
    attendance_today = await get_attendance_stats(today, today + timedelta(days=1))
    attendance_week = await get_attendance_stats(week_start, today + timedelta(days=1))
    
    # Renewals
    seven_days_later = today + timedelta(days=7)
    thirty_days_later = today + timedelta(days=30)
    renewals_7_days = await db.enrollments.count_documents({
        "end_date": {"$lte": seven_days_later, "$gte": today},
        "status": "active"
    })
    renewals_30_days = await db.enrollments.count_documents({
        "end_date": {"$lte": thirty_days_later, "$gte": today},
        "status": "active"
    })
    
    # Coach statistics
    total_coaches = await db.users.count_documents({"role": "coach", "active": {"$ne": False}})
    
    # Today's classes
    day_name = today.strftime("%A")
    classes_today = await db.classes.count_documents({"day_of_week": day_name})
    
    # Overall occupancy
    occupancy = await calculate_overall_occupancy(centre_id)
    
    # Recent announcements
    announcements = await db.announcements.find({}).sort("sent_at", -1).limit(5).to_list(5)
    
    dashboard_data = EnhancedDashboardStats(
        total_enrollments=total_enrollments,
        active_enrollments=active_enrollments,
        paused_enrollments=paused_enrollments,
        expired_enrollments=expired_enrollments,
        revenue_today=revenue_today,
        revenue_this_week=revenue_this_week,
        revenue_this_month=revenue_this_month,
        revenue_by_centre=revenue_by_centre,
        attendance_today_percentage=attendance_today,
        attendance_this_week_percentage=attendance_week,
        missed_classes_today=0,  # TODO: Calculate
        renewals_due_7_days=renewals_7_days,
        renewals_due_30_days=renewals_30_days,
        renewal_conversion_rate=85.0,  # TODO: Calculate from historical data
        total_active_coaches=total_coaches,
        coaches_on_duty_today=0,  # TODO: Calculate from today's classes
        overall_occupancy_percentage=occupancy,
        classes_today=classes_today,
        classes_this_week=0,  # TODO: Calculate
        recent_announcements=[],  # Format announcements
        pending_actions=0
    )
    
    return jsonable_encoder(dashboard_data)

# ==================== 2. MEMBERS & ENROLLMENT MANAGEMENT ====================

@admin_router.get("/members")
async def get_all_members(
    centre_id: Optional[str] = None,
    program_id: Optional[str] = None,
    status: Optional[str] = None,
    search: Optional[str] = None,
    page: int = 1,
    limit: int = 50,
    current_user: dict = Depends(get_current_user)
):
    """
    Get all members with advanced filtering
    Supports pagination, search, and filters by centre, program, status
    """
    if current_user.get("role") not in ["admin", "franchise"]:
        raise HTTPException(status_code=403, detail="Not authorized")
    
    # Build query
    query = {}
    if search:
        query["$or"] = [
            {"name": {"$regex": search, "$options": "i"}},
            {"phone": {"$regex": search, "$options": "i"}}
        ]
    
    # Get parents (members)
    skip = (page - 1) * limit
    parents = await db.users.find({"role": "parent"}).skip(skip).limit(limit).to_list(limit)
    
    # Enrich with children and enrollment data
    members_data = []
    for parent in parents:
        children = await db.children.find({"parent_id": parent["id"]}).to_list(100)
        child_ids = [c["id"] for c in children]
        
        enrollments = await db.enrollments.find({"child_id": {"$in": child_ids}}).to_list(100)
        
        # Apply filters
        if centre_id or program_id or status:
            filtered_enrollments = []
            for enrollment in enrollments:
                if status and enrollment.get("status") != status:
                    continue
                
                # Check centre
                if centre_id:
                    class_doc = await db.classes.find_one({"id": enrollment["class_id"]})
                    if class_doc and class_doc.get("location_id") != centre_id:
                        continue
                
                # Check program
                if program_id:
                    class_doc = await db.classes.find_one({"id": enrollment["class_id"]})
                    if class_doc and class_doc.get("program_id") != program_id:
                        continue
                
                filtered_enrollments.append(enrollment)
            
            if not filtered_enrollments:
                continue
            enrollments = filtered_enrollments
        
        # Calculate attendance
        attendance_records = await db.attendance.find({"child_id": {"$in": child_ids}}).to_list(1000)
        total_sessions = len(attendance_records)
        attended = sum(1 for a in attendance_records if a.get("status") == "present")
        attendance_rate = (attended / total_sessions * 100) if total_sessions > 0 else 0
        
        members_data.append({
            "parent_id": parent["id"],
            "parent_name": parent.get("name"),
            "parent_phone": parent.get("phone"),
            "parent_email": parent.get("email"),
            "children": [serialize_doc(c) for c in children],
            "active_enrollments": len([e for e in enrollments if e.get("status") == "active"]),
            "attendance_rate": round(attendance_rate, 2),
            "join_date": parent.get("created_at")
        })
    
    total_count = await db.users.count_documents({"role": "parent"})
    
    return {
        "members": members_data,
        "total": total_count,
        "page": page,
        "pages": (total_count + limit - 1) // limit
    }

@admin_router.get("/members/{member_id}/details")
async def get_member_details(
    member_id: str,
    current_user: dict = Depends(get_current_user)
):
    """Get comprehensive member details"""
    if current_user.get("role") not in ["admin", "franchise"]:
        raise HTTPException(status_code=403, detail="Not authorized")
    
    # Get parent
    parent = await db.users.find_one({"id": member_id, "role": "parent"})
    if not parent:
        raise HTTPException(status_code=404, detail="Member not found")
    
    # Get children
    children = await db.children.find({"parent_id": member_id}).to_list(100)
    child_ids = [c["id"] for c in children]
    
    # Get enrollments
    enrollments = await db.enrollments.find({"child_id": {"$in": child_ids}}).to_list(100)
    
    # Enrich enrollments with class and program details
    enriched_enrollments = []
    for enrollment in enrollments:
        class_doc = await db.classes.find_one({"id": enrollment["class_id"]})
        if class_doc:
            program = await db.programs.find_one({"id": class_doc["program_id"]})
            location = await db.locations.find_one({"id": class_doc["location_id"]})
            
            enriched_enrollments.append({
                **enrollment,
                "program_name": program.get("name") if program else "",
                "location_name": location.get("name") if location else "",
                "class_time": f"{class_doc.get('day_of_week')} {class_doc.get('start_time')}"
            })
    
    # Get payments
    enrollment_ids = [e["id"] for e in enrollments]
    payments = await db.payments.find({"enrollment_id": {"$in": enrollment_ids}}).to_list(100)
    total_spent = sum(p.get("total_amount", 0) for p in payments if p.get("status") == "success")
    
    # Get attendance
    attendance = await db.attendance.find({"child_id": {"$in": child_ids}}).to_list(1000)
    total_sessions = len(attendance)
    attended = sum(1 for a in attendance if a.get("status") == "present")
    
    # Get last visit
    last_attendance = await db.attendance.find({"child_id": {"$in": child_ids}}).sort("date", -1).limit(1).to_list(1)
    last_visit = last_attendance[0].get("date") if last_attendance else None
    
    return MemberDetails(
        member_id=member_id,
        parent_name=parent.get("name", ""),
        parent_phone=parent.get("phone", ""),
        parent_email=parent.get("email"),
        children=children,
        active_enrollments=enriched_enrollments,
        attendance_summary={
            "total_sessions": total_sessions,
            "attended": attended,
            "rate": round((attended / total_sessions * 100) if total_sessions > 0 else 0, 2)
        },
        payment_history=payments,
        makeup_credits=sum(e.get("makeup_credits", 0) for e in enrollments),
        total_spent=total_spent,
        join_date=parent.get("created_at"),
        last_visit=last_visit
    )

# ==================== 3. COACHES & STAFF MANAGEMENT ====================

@admin_router.get("/coaches")
async def get_all_coaches(
    location_id: Optional[str] = None,
    active_only: bool = True,
    current_user: dict = Depends(get_current_user)
):
    """Get all coaches with performance metrics"""
    if current_user.get("role") not in ["admin", "franchise"]:
        raise HTTPException(status_code=403, detail="Not authorized")
    
    query = {"role": "coach"}
    if active_only:
        query["active"] = {"$ne": False}
    
    coaches = await db.users.find(query).to_list(100)
    
    coach_data = []
    for coach in coaches:
        # Get assigned classes
        classes = await db.classes.find({"coach_id": coach["id"]}).to_list(100)
        
        # Get attendance records marked by this coach
        attendance_marked = await db.attendance.count_documents({"marked_by": coach["id"]})
        
        # Get unique locations
        location_ids = list(set([c["location_id"] for c in classes]))
        locations = await db.locations.find({"id": {"$in": location_ids}}).to_list(10)
        
        coach_data.append({
            "id": coach["id"],
            "name": coach.get("name"),
            "phone": coach.get("phone"),
            "email": coach.get("email"),
            "assigned_locations": [l["name"] for l in locations],
            "total_classes": len(classes),
            "attendance_marked": attendance_marked,
            "active": coach.get("active", True),
            "specializations": [],  # TODO: Add specializations field
            "rating": 0.0,  # TODO: Calculate from feedback
            "punctuality_score": 100.0  # TODO: Calculate from attendance logs
        })
    
    return {"coaches": coach_data, "total": len(coach_data)}

@admin_router.post("/coaches")
async def create_coach(
    coach_data: dict,
    current_user: dict = Depends(get_current_user)
):
    """Create new coach"""
    if current_user.get("role") not in ["admin", "franchise"]:
        raise HTTPException(status_code=403, detail="Not authorized")
    
    from auth import get_password_hash
    import uuid
    
    new_coach = {
        "id": str(uuid.uuid4()),
        "phone": coach_data["phone"],
        "name": coach_data["name"],
        "email": coach_data.get("email"),
        "role": "coach",
        "password": get_password_hash(coach_data.get("password", "coach123")),
        "active": True,
        "created_at": datetime.utcnow(),
        "referral_code": f"COACH{coach_data['phone'][-4:]}"
    }
    
    await db.users.insert_one(new_coach)
    return {"success": True, "coach_id": new_coach["id"]}

@admin_router.patch("/coaches/{coach_id}")
async def update_coach(
    coach_id: str,
    updates: dict,
    current_user: dict = Depends(get_current_user)
):
    """Update coach details"""
    if current_user.get("role") not in ["admin", "franchise"]:
        raise HTTPException(status_code=403, detail="Not authorized")
    
    await db.users.update_one(
        {"id": coach_id, "role": "coach"},
        {"$set": updates}
    )
    return {"success": True}

# ==================== 4. CLASS & SCHEDULE MANAGEMENT ====================

@admin_router.get("/schedule")
async def get_schedule(
    centre_id: Optional[str] = None,
    coach_id: Optional[str] = None,
    program_id: Optional[str] = None,
    view: str = "week",  # "week" or "month"
    current_user: dict = Depends(get_current_user)
):
    """Get class schedule with occupancy details"""
    if current_user.get("role") not in ["admin", "franchise"]:
        raise HTTPException(status_code=403, detail="Not authorized")
    
    query = {}
    if centre_id:
        query["location_id"] = centre_id
    if coach_id:
        query["coach_id"] = coach_id
    if program_id:
        query["program_id"] = program_id
    
    classes = await db.classes.find(query).to_list(1000)
    
    schedule_details = []
    for cls in classes:
        # Get enrollment count
        enrollments = await db.enrollments.count_documents({
            "class_id": cls["id"],
            "status": "active"
        })
        
        # Get program and location details
        program = await db.programs.find_one({"id": cls["program_id"]})
        location = await db.locations.find_one({"id": cls["location_id"]})
        coach = await db.users.find_one({"id": cls["coach_id"]})
        
        occupancy = (enrollments / cls["capacity"] * 100) if cls["capacity"] > 0 else 0
        
        schedule_details.append(ClassScheduleDetail(
            id=cls["id"],
            program_name=program.get("name", "") if program else "",
            level=program.get("level", "") if program else "",
            location_name=location.get("name", "") if location else "",
            coach_name=coach.get("name", "") if coach else "",
            day_of_week=cls["day_of_week"],
            start_time=cls["start_time"],
            end_time=cls["end_time"],
            capacity=cls["capacity"],
            enrolled_count=enrollments,
            occupancy_percentage=round(occupancy, 2),
            waitlist_count=0  # TODO: Implement waitlist
        ))
    
    return {"schedule": schedule_details, "total": len(schedule_details)}

@admin_router.post("/schedule/class")
async def create_class(
    class_data: ClassCreate,
    current_user: dict = Depends(get_current_user)
):
    """Create new class"""
    if current_user.get("role") not in ["admin", "franchise"]:
        raise HTTPException(status_code=403, detail="Not authorized")
    
    new_class = Class(**class_data.dict())
    await db.classes.insert_one(new_class.dict())
    return {"success": True, "class_id": new_class.id}

@admin_router.patch("/schedule/class/{class_id}")
async def update_class(
    class_id: str,
    updates: dict,
    current_user: dict = Depends(get_current_user)
):
    """Update class details"""
    if current_user.get("role") not in ["admin", "franchise"]:
        raise HTTPException(status_code=403, detail="Not authorized")
    
    await db.classes.update_one(
        {"id": class_id},
        {"$set": updates}
    )
    return {"success": True}

@admin_router.delete("/schedule/class/{class_id}")
async def delete_class(
    class_id: str,
    current_user: dict = Depends(get_current_user)
):
    """Delete class"""
    if current_user.get("role") not in ["admin", "franchise"]:
        raise HTTPException(status_code=403, detail="Not authorized")
    
    await db.classes.delete_one({"id": class_id})
    return {"success": True}

# ==================== 5. PAYMENTS & RENEWALS ====================

@admin_router.get("/payments")
async def get_all_payments(
    centre_id: Optional[str] = None,
    status: Optional[str] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    page: int = 1,
    limit: int = 50,
    current_user: dict = Depends(get_current_user)
):
    """Get all payments with filtering"""
    if current_user.get("role") not in ["admin", "franchise"]:
        raise HTTPException(status_code=403, detail="Not authorized")
    
    query = {}
    if status:
        query["status"] = status
    
    if start_date and end_date:
        query["created_at"] = {
            "$gte": datetime.fromisoformat(start_date),
            "$lte": datetime.fromisoformat(end_date)
        }
    
    skip = (page - 1) * limit
    payments = await db.payments.find(query).sort("created_at", -1).skip(skip).limit(limit).to_list(limit)
    
    # Enrich with enrollment details
    enriched_payments = []
    for payment in payments:
        enrollment = await db.enrollments.find_one({"id": payment["enrollment_id"]})
        if enrollment:
            child = await db.children.find_one({"id": enrollment["child_id"]})
            enriched_payment = serialize_doc({
                **payment,
                "child_name": child.get("name") if child else "",
                "plan_type": enrollment.get("plan_type")
            })
            enriched_payments.append(enriched_payment)
        else:
            enriched_payments.append(serialize_doc(payment))
    
    total = await db.payments.count_documents(query)
    
    return {
        "payments": enriched_payments,
        "total": total,
        "page": page,
        "pages": (total + limit - 1) // limit
    }

@admin_router.get("/renewals")
async def get_renewals(
    days_ahead: int = 30,
    current_user: dict = Depends(get_current_user)
):
    """Get enrollments due for renewal"""
    if current_user.get("role") not in ["admin", "franchise"]:
        raise HTTPException(status_code=403, detail="Not authorized")
    
    today = datetime.utcnow()
    future_date = today + timedelta(days=days_ahead)
    
    enrollments = await db.enrollments.find({
        "end_date": {"$lte": future_date, "$gte": today},
        "status": "active"
    }).to_list(1000)
    
    # Enrich with child and parent details
    renewal_data = []
    for enrollment in enrollments:
        child = await db.children.find_one({"id": enrollment["child_id"]})
        if child:
            parent = await db.users.find_one({"id": child["parent_id"]})
            class_doc = await db.classes.find_one({"id": enrollment["class_id"]})
            program = await db.programs.find_one({"id": class_doc["program_id"]}) if class_doc else None
            
            days_until_expiry = (enrollment["end_date"] - today).days if isinstance(enrollment["end_date"], date) else 0
            
            renewal_data.append({
                "enrollment_id": enrollment["id"],
                "child_name": child.get("name"),
                "parent_name": parent.get("name") if parent else "",
                "parent_phone": parent.get("phone") if parent else "",
                "program_name": program.get("name") if program else "",
                "expiry_date": enrollment["end_date"],
                "days_until_expiry": days_until_expiry,
                "plan_type": enrollment["plan_type"]
            })
    
    return {"renewals": renewal_data, "total": len(renewal_data)}

# ==================== HELPER FUNCTIONS ====================

async def calculate_revenue(start_date: datetime, end_date: datetime, centre_id: Optional[str] = None) -> float:
    """Calculate revenue for given period"""
    query = {
        "status": "success",
        "created_at": {"$gte": start_date, "$lt": end_date}
    }
    
    payments = await db.payments.find(query).to_list(10000)
    return sum(p.get("total_amount", 0) for p in payments)

async def get_revenue_by_centre() -> Dict[str, float]:
    """Get revenue breakdown by centre"""
    locations = await db.locations.find({}).to_list(100)
    revenue_by_centre = {}
    
    for location in locations:
        # Get classes at this location
        classes = await db.classes.find({"location_id": location["id"]}).to_list(1000)
        class_ids = [c["id"] for c in classes]
        
        # Get enrollments for these classes
        enrollments = await db.enrollments.find({"class_id": {"$in": class_ids}}).to_list(1000)
        enrollment_ids = [e["id"] for e in enrollments]
        
        # Get successful payments
        payments = await db.payments.find({
            "enrollment_id": {"$in": enrollment_ids},
            "status": "success"
        }).to_list(1000)
        
        total = sum(p.get("total_amount", 0) for p in payments)
        revenue_by_centre[location["name"]] = total
    
    return revenue_by_centre

async def get_attendance_stats(start_date: datetime, end_date: datetime) -> float:
    """Calculate attendance rate for given period"""
    attendance = await db.attendance.find({
        "date": {"$gte": start_date, "$lt": end_date}
    }).to_list(10000)
    
    if not attendance:
        return 0.0
    
    present = sum(1 for a in attendance if a.get("status") == "present")
    return round((present / len(attendance) * 100), 2)

async def calculate_overall_occupancy(centre_id: Optional[str] = None) -> float:
    """Calculate overall occupancy percentage"""
    query = {}
    if centre_id:
        query["location_id"] = centre_id
    
    classes = await db.classes.find(query).to_list(1000)
    
    total_capacity = 0
    total_enrolled = 0
    
    for cls in classes:
        total_capacity += cls.get("capacity", 0)
        enrolled = await db.enrollments.count_documents({
            "class_id": cls["id"],
            "status": "active"
        })
        total_enrolled += enrolled
    
    if total_capacity == 0:
        return 0.0
    
    return round((total_enrolled / total_capacity * 100), 2)

# ==================== 6. CRM & COMMUNICATION HUB ====================

@admin_router.get("/crm/leads")
async def get_all_leads(
    status: Optional[str] = None,
    source: Optional[str] = None,
    location_id: Optional[str] = None,
    page: int = 1,
    limit: int = 50,
    current_user: dict = Depends(get_current_user)
):
    """Get all leads with filtering"""
    if current_user.get("role") not in ["admin", "franchise"]:
        raise HTTPException(status_code=403, detail="Not authorized")
    
    query = {}
    if status:
        query["status"] = status
    if source:
        query["source"] = source
    if location_id:
        query["location_id"] = location_id
    
    skip = (page - 1) * limit
    leads = await db.leads.find(query).sort("created_at", -1).skip(skip).limit(limit).to_list(limit)
    total = await db.leads.count_documents(query)
    
    # Serialize leads to handle ObjectId
    serialized_leads = [serialize_doc(lead) for lead in leads]
    
    return {
        "leads": serialized_leads,
        "total": total,
        "page": page,
        "pages": (total + limit - 1) // limit
    }

@admin_router.patch("/crm/leads/{lead_id}")
async def update_lead(
    lead_id: str,
    updates: dict,
    current_user: dict = Depends(get_current_user)
):
    """Update lead status and notes"""
    if current_user.get("role") not in ["admin", "franchise"]:
        raise HTTPException(status_code=403, detail="Not authorized")
    
    await db.leads.update_one(
        {"id": lead_id},
        {"$set": updates}
    )
    return {"success": True}

@admin_router.post("/communication/campaigns")
async def create_campaign(
    campaign_data: dict,
    current_user: dict = Depends(get_current_user)
):
    """Create communication campaign"""
    if current_user.get("role") not in ["admin", "franchise"]:
        raise HTTPException(status_code=403, detail="Not authorized")
    
    import uuid
    
    campaign = {
        "id": str(uuid.uuid4()),
        "name": campaign_data["name"],
        "message_template": campaign_data["message_template"],
        "audience_filter": campaign_data.get("audience_filter", {}),
        "channels": campaign_data.get("channels", ["push"]),
        "schedule_type": campaign_data.get("schedule_type", "immediate"),
        "schedule_time": campaign_data.get("schedule_time"),
        "status": "draft",
        "sent_count": 0,
        "delivered_count": 0,
        "opened_count": 0,
        "created_by": current_user["sub"],
        "created_at": datetime.utcnow()
    }
    
    await db.campaigns.insert_one(campaign)
    return {"success": True, "campaign_id": campaign["id"]}

@admin_router.post("/communication/campaigns/{campaign_id}/send")
async def send_campaign(
    campaign_id: str,
    current_user: dict = Depends(get_current_user)
):
    """Send campaign to target audience"""
    if current_user.get("role") not in ["admin", "franchise"]:
        raise HTTPException(status_code=403, detail="Not authorized")
    
    campaign = await db.campaigns.find_one({"id": campaign_id})
    if not campaign:
        raise HTTPException(status_code=404, detail="Campaign not found")
    
    # Get target audience based on filters
    audience_filter = campaign.get("audience_filter", {})
    
    # Build query for target users
    user_query = {}
    if audience_filter.get("role"):
        user_query["role"] = audience_filter["role"]
    if audience_filter.get("location_id"):
        # Get users with children enrolled at this location
        # This is simplified - in production, you'd have more complex filtering
        pass
    
    target_users = await db.users.find(user_query).to_list(10000)
    
    # TODO: Integrate with actual messaging services
    # - Push notifications: Firebase Cloud Messaging
    # - WhatsApp: Twilio/MSG91 API
    # - Email: SendGrid/Amazon SES
    # - SMS: Twilio/MSG91 API
    
    # For now, just mark as sent
    sent_count = len(target_users)
    
    await db.campaigns.update_one(
        {"id": campaign_id},
        {"$set": {
            "status": "sent",
            "sent_count": sent_count,
            "sent_at": datetime.utcnow()
        }}
    )
    
    logger.info(f"Campaign {campaign_id} sent to {sent_count} users")
    
    return {
        "success": True,
        "sent_count": sent_count,
        "message": "Campaign sent successfully. Integration with messaging services pending."
    }

@admin_router.get("/communication/campaigns")
async def get_campaigns(
    status: Optional[str] = None,
    current_user: dict = Depends(get_current_user)
):
    """Get all campaigns"""
    if current_user.get("role") not in ["admin", "franchise"]:
        raise HTTPException(status_code=403, detail="Not authorized")
    
    query = {}
    if status:
        query["status"] = status
    
    campaigns = await db.campaigns.find(query).sort("created_at", -1).to_list(100)
    return {"campaigns": campaigns, "total": len(campaigns)}

# ==================== 7. REPORTS & ANALYTICS ====================

@admin_router.get("/reports/enrollments")
async def get_enrollment_report(
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    centre_id: Optional[str] = None,
    brand: Optional[str] = None,
    current_user: dict = Depends(get_current_user)
):
    """Generate enrollment report"""
    if current_user.get("role") not in ["admin", "franchise"]:
        raise HTTPException(status_code=403, detail="Not authorized")
    
    query = {}
    if start_date and end_date:
        query["created_at"] = {
            "$gte": datetime.fromisoformat(start_date),
            "$lte": datetime.fromisoformat(end_date)
        }
    
    enrollments = await db.enrollments.find(query).to_list(10000)
    
    # Calculate statistics
    total = len(enrollments)
    new_enrollments = len([e for e in enrollments if e.get("payment_id")])
    renewals = 0  # TODO: Track renewals separately
    cancellations = len([e for e in enrollments if e.get("status") == "cancelled"])
    
    # Group by plan
    by_plan = {}
    for e in enrollments:
        plan = e.get("plan_type", "unknown")
        by_plan[plan] = by_plan.get(plan, 0) + 1
    
    # Group by centre
    by_centre = {}
    for e in enrollments:
        class_doc = await db.classes.find_one({"id": e["class_id"]})
        if class_doc:
            location = await db.locations.find_one({"id": class_doc["location_id"]})
            if location:
                centre_name = location["name"]
                by_centre[centre_name] = by_centre.get(centre_name, 0) + 1
    
    # TODO: Generate trend data (daily/weekly/monthly)
    trend_data = []
    
    return EnrollmentReport(
        total_enrollments=total,
        new_enrollments=new_enrollments,
        renewals=renewals,
        cancellations=cancellations,
        by_plan=by_plan,
        by_brand={"tumble_gym": 0, "tumble_fit": 0, "tumble_gold": 0},  # TODO: Calculate
        by_centre=by_centre,
        trend_data=trend_data
    )

@admin_router.get("/reports/revenue")
async def get_revenue_report(
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    centre_id: Optional[str] = None,
    current_user: dict = Depends(get_current_user)
):
    """Generate revenue report"""
    if current_user.get("role") not in ["admin", "franchise"]:
        raise HTTPException(status_code=403, detail="Not authorized")
    
    query = {"status": "success"}
    if start_date and end_date:
        query["created_at"] = {
            "$gte": datetime.fromisoformat(start_date),
            "$lte": datetime.fromisoformat(end_date)
        }
    
    payments = await db.payments.find(query).to_list(10000)
    
    total_revenue = sum(p.get("total_amount", 0) for p in payments)
    refunds = sum(p.get("total_amount", 0) for p in await db.payments.find({"status": "refunded"}).to_list(1000))
    
    # Group by centre
    by_centre = {}
    for p in payments:
        enrollment = await db.enrollments.find_one({"id": p["enrollment_id"]})
        if enrollment:
            class_doc = await db.classes.find_one({"id": enrollment["class_id"]})
            if class_doc:
                location = await db.locations.find_one({"id": class_doc["location_id"]})
                if location:
                    centre_name = location["name"]
                    by_centre[centre_name] = by_centre.get(centre_name, 0) + p.get("total_amount", 0)
    
    return RevenueReport(
        total_revenue=total_revenue,
        by_centre=by_centre,
        by_plan={},  # TODO: Calculate
        by_payment_method={"razorpay": total_revenue},  # Simplified
        refunds=refunds,
        net_revenue=total_revenue - refunds,
        trend_data=[]  # TODO: Generate
    )

@admin_router.get("/reports/attendance")
async def get_attendance_report(
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    centre_id: Optional[str] = None,
    program_id: Optional[str] = None,
    current_user: dict = Depends(get_current_user)
):
    """Generate attendance report"""
    if current_user.get("role") not in ["admin", "franchise"]:
        raise HTTPException(status_code=403, detail="Not authorized")
    
    query = {}
    if start_date and end_date:
        query["date"] = {
            "$gte": datetime.fromisoformat(start_date),
            "$lte": datetime.fromisoformat(end_date)
        }
    
    attendance = await db.attendance.find(query).to_list(10000)
    
    total_sessions = len(attendance)
    attended = len([a for a in attendance if a.get("status") == "present"])
    absent = len([a for a in attendance if a.get("status") == "absent"])
    makeup = len([a for a in attendance if a.get("status") == "makeup"])
    
    attendance_rate = (attended / total_sessions * 100) if total_sessions > 0 else 0
    
    # Group by day
    by_day = {}
    for a in attendance:
        day = a.get("date").strftime("%A") if a.get("date") else "Unknown"
        by_day[day] = by_day.get(day, 0) + 1
    
    return AttendanceReport(
        total_sessions=total_sessions,
        attended_sessions=attended,
        absent_sessions=absent,
        makeup_sessions=makeup,
        attendance_rate=round(attendance_rate, 2),
        by_centre={},  # TODO: Calculate
        by_program={},  # TODO: Calculate
        by_day=by_day
    )

@admin_router.get("/reports/export/{report_type}")
async def export_report(
    report_type: str,
    format: str = "csv",  # csv, excel, pdf
    current_user: dict = Depends(get_current_user)
):
    """Export reports in various formats"""
    if current_user.get("role") not in ["admin", "franchise"]:
        raise HTTPException(status_code=403, detail="Not authorized")
    
    # TODO: Implement actual export functionality
    # - CSV: Use Python csv module
    # - Excel: Use openpyxl or xlsxwriter
    # - PDF: Use reportlab or WeasyPrint
    
    return {
        "success": True,
        "message": f"Export feature for {report_type} in {format} format coming soon",
        "download_url": None
    }

# ==================== 8. ANNOUNCEMENTS & NOTIFICATIONS ====================

@admin_router.post("/announcements")
async def create_announcement(
    announcement_data: dict,
    current_user: dict = Depends(get_current_user)
):
    """Create and send announcement"""
    if current_user.get("role") not in ["admin", "franchise"]:
        raise HTTPException(status_code=403, detail="Not authorized")
    
    import uuid
    
    announcement = {
        "id": str(uuid.uuid4()),
        "title": announcement_data["title"],
        "message": announcement_data["message"],
        "audience": announcement_data.get("audience", "all"),
        "channels": announcement_data.get("channels", ["push"]),
        "created_by": current_user["sub"],
        "sent_at": datetime.utcnow()
    }
    
    await db.announcements.insert_one(announcement)
    
    # TODO: Send via actual channels (Push, WhatsApp, Email)
    logger.info(f"Announcement created: {announcement['title']}")
    
    return {"success": True, "announcement_id": announcement["id"]}

@admin_router.get("/announcements")
async def get_announcements(
    page: int = 1,
    limit: int = 20,
    current_user: dict = Depends(get_current_user)
):
    """Get all announcements"""
    if current_user.get("role") not in ["admin", "franchise"]:
        raise HTTPException(status_code=403, detail="Not authorized")
    
    skip = (page - 1) * limit
    announcements = await db.announcements.find({}).sort("sent_at", -1).skip(skip).limit(limit).to_list(limit)
    total = await db.announcements.count_documents({})
    
    return {
        "announcements": announcements,
        "total": total,
        "page": page,
        "pages": (total + limit - 1) // limit
    }

# ==================== 9. OFFERS & COUPONS ====================

@admin_router.post("/offers")
async def create_offer(
    offer_data: dict,
    current_user: dict = Depends(get_current_user)
):
    """Create new offer/coupon"""
    if current_user.get("role") not in ["admin", "franchise"]:
        raise HTTPException(status_code=403, detail="Not authorized")
    
    import uuid
    
    offer = {
        "id": str(uuid.uuid4()),
        "title": offer_data["title"],
        "description": offer_data["description"],
        "discount_type": offer_data["discount_type"],
        "discount_value": offer_data["discount_value"],
        "applicable_plans": offer_data.get("applicable_plans", []),
        "locations": offer_data.get("locations"),
        "brands": offer_data.get("brands"),
        "valid_from": datetime.fromisoformat(offer_data["valid_from"]) if isinstance(offer_data.get("valid_from"), str) else offer_data["valid_from"],
        "valid_to": datetime.fromisoformat(offer_data["valid_to"]) if isinstance(offer_data.get("valid_to"), str) else offer_data["valid_to"],
        "max_redemptions": offer_data.get("max_redemptions"),
        "redemptions": 0,
        "created_by": current_user["sub"],
        "created_at": datetime.utcnow()
    }
    
    await db.offers.insert_one(offer)
    return {"success": True, "offer_id": offer["id"]}

@admin_router.get("/offers")
async def get_offers(
    active_only: bool = False,
    current_user: dict = Depends(get_current_user)
):
    """Get all offers"""
    if current_user.get("role") not in ["admin", "franchise"]:
        raise HTTPException(status_code=403, detail="Not authorized")
    
    query = {}
    if active_only:
        today = datetime.now()
        query["valid_from"] = {"$lte": today}
        query["valid_to"] = {"$gte": today}
    
    offers = await db.offers.find(query).sort("created_at", -1).to_list(100)
    return {"offers": offers, "total": len(offers)}

@admin_router.get("/offers/{offer_id}/stats")
async def get_offer_stats(
    offer_id: str,
    current_user: dict = Depends(get_current_user)
):
    """Get offer redemption statistics"""
    if current_user.get("role") not in ["admin", "franchise"]:
        raise HTTPException(status_code=403, detail="Not authorized")
    
    offer = await db.offers.find_one({"id": offer_id})
    if not offer:
        raise HTTPException(status_code=404, detail="Offer not found")
    
    # TODO: Track redemptions in enrollments/payments
    redemptions = offer.get("redemptions", 0)
    max_redemptions = offer.get("max_redemptions", 0)
    
    # Calculate revenue impact
    # TODO: Calculate actual revenue from enrollments using this offer
    revenue_impact = 0.0
    
    return {
        "offer_id": offer_id,
        "title": offer["title"],
        "redemptions": redemptions,
        "max_redemptions": max_redemptions,
        "remaining": max(0, max_redemptions - redemptions) if max_redemptions else "Unlimited",
        "revenue_impact": revenue_impact,
        "conversion_rate": 0.0  # TODO: Calculate
    }

@admin_router.post("/coupons")
async def create_coupon(
    coupon_data: dict,
    current_user: dict = Depends(get_current_user)
):
    """Create coupon code"""
    if current_user.get("role") not in ["admin", "franchise"]:
        raise HTTPException(status_code=403, detail="Not authorized")
    
    import uuid
    
    coupon = {
        "id": str(uuid.uuid4()),
        "code": coupon_data["code"].upper(),
        "discount_type": coupon_data["discount_type"],
        "discount_value": coupon_data["discount_value"],
        "max_redemptions": coupon_data.get("max_redemptions", 100),
        "valid_from": datetime.fromisoformat(coupon_data["valid_from"]) if isinstance(coupon_data.get("valid_from"), str) else coupon_data["valid_from"],
        "valid_to": datetime.fromisoformat(coupon_data["valid_to"]) if isinstance(coupon_data.get("valid_to"), str) else coupon_data["valid_to"],
        "locations": coupon_data.get("locations"),
        "redemptions": 0,
        "created_at": datetime.utcnow()
    }
    
    await db.coupons.insert_one(coupon)
    return {"success": True, "coupon_id": coupon["id"], "code": coupon["code"]}

@admin_router.get("/coupons")
async def get_coupons(
    current_user: dict = Depends(get_current_user)
):
    """Get all coupons"""
    if current_user.get("role") not in ["admin", "franchise"]:
        raise HTTPException(status_code=403, detail="Not authorized")
    
    coupons = await db.coupons.find({}).sort("created_at", -1).to_list(100)
    return {"coupons": coupons, "total": len(coupons)}

# ==================== 10. MULTI-CENTRE MANAGEMENT ====================

@admin_router.get("/centres/overview")
async def get_centres_overview(
    current_user: dict = Depends(get_current_user)
):
    """Get overview of all centres"""
    if current_user.get("role") not in ["admin", "franchise"]:
        raise HTTPException(status_code=403, detail="Not authorized")
    
    locations = await db.locations.find({}).to_list(100)
    
    centres_data = []
    for location in locations:
        # Get classes at this centre
        classes = await db.classes.find({"location_id": location["id"]}).to_list(1000)
        class_ids = [c["id"] for c in classes]
        
        # Get active enrollments
        enrollments = await db.enrollments.count_documents({
            "class_id": {"$in": class_ids},
            "status": "active"
        })
        
        # Get revenue
        enrollment_docs = await db.enrollments.find({"class_id": {"$in": class_ids}}).to_list(1000)
        enrollment_ids = [e["id"] for e in enrollment_docs]
        payments = await db.payments.find({
            "enrollment_id": {"$in": enrollment_ids},
            "status": "success"
        }).to_list(1000)
        revenue = sum(p.get("total_amount", 0) for p in payments)
        
        # Get attendance rate
        attendance = await db.attendance.find({
            "class_id": {"$in": class_ids}
        }).to_list(10000)
        total_attendance = len(attendance)
        present = len([a for a in attendance if a.get("status") == "present"])
        attendance_rate = (present / total_attendance * 100) if total_attendance > 0 else 0
        
        # Get coaches
        coach_ids = list(set([c["coach_id"] for c in classes]))
        
        # Calculate occupancy
        total_capacity = sum(c.get("capacity", 0) for c in classes)
        occupancy = (enrollments / total_capacity * 100) if total_capacity > 0 else 0
        
        centres_data.append({
            "id": location["id"],
            "name": location["name"],
            "city": location["city"],
            "enrollments": enrollments,
            "revenue": revenue,
            "attendance_rate": round(attendance_rate, 2),
            "occupancy": round(occupancy, 2),
            "total_classes": len(classes),
            "total_coaches": len(coach_ids)
        })
    
    return {"centres": centres_data, "total": len(centres_data)}

@admin_router.get("/centres/{centre_id}/details")
async def get_centre_details(
    centre_id: str,
    current_user: dict = Depends(get_current_user)
):
    """Get detailed centre information"""
    if current_user.get("role") not in ["admin", "franchise"]:
        raise HTTPException(status_code=403, detail="Not authorized")
    
    location = await db.locations.find_one({"id": centre_id})
    if not location:
        raise HTTPException(status_code=404, detail="Centre not found")
    
    # Get all related data
    classes = await db.classes.find({"location_id": centre_id}).to_list(1000)
    class_ids = [c["id"] for c in classes]
    
    enrollments = await db.enrollments.find({"class_id": {"$in": class_ids}}).to_list(1000)
    
    # Detailed stats
    stats = {
        "location": location,
        "total_classes": len(classes),
        "total_enrollments": len(enrollments),
        "active_enrollments": len([e for e in enrollments if e.get("status") == "active"]),
        "programs_offered": len(set([c["program_id"] for c in classes])),
        "coaches_assigned": len(set([c["coach_id"] for c in classes]))
    }
    
    return stats

# ==================== 11. AI & AUTOMATION ====================

@admin_router.get("/ai/renewal-prediction")
async def predict_renewals(
    current_user: dict = Depends(get_current_user)
):
    """AI-powered renewal prediction"""
    if current_user.get("role") not in ["admin", "franchise"]:
        raise HTTPException(status_code=403, detail="Not authorized")
    
    # Get enrollments expiring in next 30 days
    today = datetime.utcnow()
    future_date = today + timedelta(days=30)
    
    enrollments = await db.enrollments.find({
        "end_date": {"$lte": future_date, "$gte": today},
        "status": "active"
    }).to_list(1000)
    
    predictions = []
    for enrollment in enrollments:
        # Get attendance history
        attendance = await db.attendance.find({"child_id": enrollment["child_id"]}).to_list(1000)
        total_sessions = len(attendance)
        attended = len([a for a in attendance if a.get("status") == "present"])
        attendance_rate = (attended / total_sessions * 100) if total_sessions > 0 else 0
        
        # Simple rule-based prediction (TODO: Replace with ML model)
        renewal_probability = 50.0  # Base probability
        
        if attendance_rate > 80:
            renewal_probability = 85.0
        elif attendance_rate > 60:
            renewal_probability = 70.0
        elif attendance_rate > 40:
            renewal_probability = 55.0
        else:
            renewal_probability = 30.0
        
        # Get child and parent details
        child = await db.children.find_one({"id": enrollment["child_id"]})
        parent = await db.users.find_one({"id": child["parent_id"]}) if child else None
        
        predictions.append({
            "enrollment_id": enrollment["id"],
            "child_name": child.get("name") if child else "",
            "parent_name": parent.get("name") if parent else "",
            "parent_phone": parent.get("phone") if parent else "",
            "expiry_date": enrollment["end_date"],
            "attendance_rate": round(attendance_rate, 2),
            "renewal_probability": renewal_probability,
            "risk_level": "high" if renewal_probability < 50 else ("medium" if renewal_probability < 75 else "low"),
            "recommended_action": "Priority follow-up" if renewal_probability < 50 else "Standard follow-up"
        })
    
    # Sort by renewal probability (lowest first - highest risk)
    predictions.sort(key=lambda x: x["renewal_probability"])
    
    return {
        "predictions": predictions,
        "total": len(predictions),
        "high_risk": len([p for p in predictions if p["risk_level"] == "high"]),
        "medium_risk": len([p for p in predictions if p["risk_level"] == "medium"]),
        "low_risk": len([p for p in predictions if p["risk_level"] == "low"])
    }

@admin_router.get("/ai/scheduling-suggestions")
async def get_scheduling_suggestions(
    centre_id: Optional[str] = None,
    current_user: dict = Depends(get_current_user)
):
    """AI-powered class scheduling suggestions"""
    if current_user.get("role") not in ["admin", "franchise"]:
        raise HTTPException(status_code=403, detail="Not authorized")
    
    query = {}
    if centre_id:
        query["location_id"] = centre_id
    
    classes = await db.classes.find(query).to_list(1000)
    
    suggestions = []
    for cls in classes:
        # Get enrollment count
        enrollments = await db.enrollments.count_documents({
            "class_id": cls["id"],
            "status": "active"
        })
        
        occupancy = (enrollments / cls["capacity"] * 100) if cls["capacity"] > 0 else 0
        
        # Generate suggestions
        if occupancy > 90:
            suggestions.append({
                "class_id": cls["id"],
                "day": cls["day_of_week"],
                "time": cls["start_time"],
                "current_occupancy": round(occupancy, 2),
                "suggestion": "Add parallel class - high demand",
                "priority": "high"
            })
        elif occupancy < 30:
            suggestions.append({
                "class_id": cls["id"],
                "day": cls["day_of_week"],
                "time": cls["start_time"],
                "current_occupancy": round(occupancy, 2),
                "suggestion": "Consider rescheduling to peak hours",
                "priority": "medium"
            })
    
    return {"suggestions": suggestions, "total": len(suggestions)}

@admin_router.get("/ai/lead-scoring")
async def score_leads(
    current_user: dict = Depends(get_current_user)
):
    """AI-powered lead scoring"""
    if current_user.get("role") not in ["admin", "franchise"]:
        raise HTTPException(status_code=403, detail="Not authorized")
    
    leads = await db.leads.find({"status": "new"}).to_list(1000)
    
    scored_leads = []
    for lead in leads:
        # Simple rule-based scoring (TODO: Replace with ML model)
        score = 50  # Base score
        
        # Source scoring
        if lead.get("source") == "referral":
            score += 30
        elif lead.get("source") == "website":
            score += 20
        elif lead.get("source") == "walk-in":
            score += 25
        
        # Recency scoring
        days_old = (datetime.utcnow() - lead["created_at"]).days
        if days_old < 2:
            score += 20
        elif days_old < 7:
            score += 10
        
        # TODO: Add more sophisticated scoring factors
        # - Email domain (corporate vs personal)
        # - Location proximity
        # - Previous interaction history
        
        scored_lead = serialize_doc({
            **lead,
            "score": min(100, score),
            "priority": "high" if score > 80 else ("medium" if score > 60 else "low")
        })
        scored_leads.append(scored_lead)
    
    # Sort by score (highest first)
    scored_leads.sort(key=lambda x: x["score"], reverse=True)
    
    return {
        "leads": scored_leads,
        "total": len(scored_leads),
        "high_priority": len([l for l in scored_leads if l["priority"] == "high"]),
        "medium_priority": len([l for l in scored_leads if l["priority"] == "medium"]),
        "low_priority": len([l for l in scored_leads if l["priority"] == "low"])
    }
