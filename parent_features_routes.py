"""
Parent App Features Routes
Attendance, Progress Reports, Leave Management, Trial Booking, Events
"""
from fastapi import APIRouter, Depends, HTTPException, Query
from typing import Optional, List
from datetime import datetime, timedelta, date
from pydantic import BaseModel
from motor.motor_asyncio import AsyncIOMotorClient
from pathlib import Path
import os
from dotenv import load_dotenv
import calendar

from auth import get_current_user

# Load environment variables
ROOT_DIR = Path(__file__).parent
load_dotenv(ROOT_DIR / '.env')

# MongoDB connection
mongo_url = os.environ['MONGO_URL']
client = AsyncIOMotorClient(mongo_url)
db = client[os.environ['DB_NAME']]

parent_features_router = APIRouter(prefix="/api/parent", tags=["Parent Features"])

# ==================== MODELS ====================

class LeaveRequest(BaseModel):
    child_id: str
    start_date: date
    end_date: date
    reason: str

class TrialBooking(BaseModel):
    child_name: str
    child_age: int
    parent_name: str
    parent_phone: str
    parent_email: Optional[str] = None
    preferred_date: date
    preferred_time: str
    center_id: str
    program_id: Optional[str] = None

class RescheduleRequest(BaseModel):
    child_id: str
    current_class_id: str
    new_class_id: str
    reason: str

# ==================== HELPER FUNCTIONS ====================

def serialize_doc(doc: dict) -> dict:
    """Convert MongoDB document to JSON-serializable dict"""
    if not doc:
        return None
    if "_id" in doc:
        del doc["_id"]
    for key, value in doc.items():
        if isinstance(value, datetime):
            doc[key] = value.isoformat()
        elif isinstance(value, date):
            doc[key] = value.isoformat()
    return doc

# ==================== ATTENDANCE TRACKING ====================

@parent_features_router.get("/attendance/{child_id}")
async def get_child_attendance(
    child_id: str,
    month: Optional[int] = None,
    year: Optional[int] = None,
    current_user: dict = Depends(get_current_user)
):
    """Get attendance records for a child"""
    try:
        # Verify child belongs to parent
        child = await db.children.find_one({"id": child_id})
        if not child:
            raise HTTPException(status_code=404, detail="Child not found")
        
        if child.get("parent_id") != current_user["sub"]:
            raise HTTPException(status_code=403, detail="Not authorized")
        
        # Set date range
        if not month or not year:
            now = datetime.utcnow()
            month = now.month
            year = now.year
        
        start_date = datetime(year, month, 1)
        if month == 12:
            end_date = datetime(year + 1, 1, 1)
        else:
            end_date = datetime(year, month + 1, 1)
        
        # Get attendance records
        attendance_records = await db.attendance.find({
            "child_id": child_id,
            "date": {"$gte": start_date.date(), "$lt": end_date.date()}
        }).to_list(1000)
        
        # Calculate statistics
        total_classes = len(attendance_records)
        present_count = sum(1 for a in attendance_records if a.get("status") == "present")
        absent_count = sum(1 for a in attendance_records if a.get("status") == "absent")
        makeup_count = sum(1 for a in attendance_records if a.get("status") == "makeup")
        
        attendance_rate = (present_count / total_classes * 100) if total_classes > 0 else 0
        
        # Get class details for each attendance
        for record in attendance_records:
            class_doc = await db.classes.find_one({"id": record.get("class_id")})
            if class_doc:
                record["class_name"] = f"{class_doc.get('day_of_week')} {class_doc.get('start_time')}"
                record["program_name"] = class_doc.get("program_name")
        
        return {
            "success": True,
            "attendance": [serialize_doc(a) for a in attendance_records],
            "statistics": {
                "total_classes": total_classes,
                "present": present_count,
                "absent": absent_count,
                "makeup": makeup_count,
                "attendance_rate": round(attendance_rate, 2)
            },
            "month": month,
            "year": year
        }
    
    except HTTPException as he:
        raise he
    except Exception as e:
        print(f"Error getting attendance: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@parent_features_router.get("/attendance/{child_id}/calendar")
async def get_attendance_calendar(
    child_id: str,
    month: int,
    year: int,
    current_user: dict = Depends(get_current_user)
):
    """Get attendance calendar view for a month"""
    try:
        # Verify child belongs to parent
        child = await db.children.find_one({"id": child_id})
        if not child or child.get("parent_id") != current_user["sub"]:
            raise HTTPException(status_code=403, detail="Not authorized")
        
        # Get attendance for the month
        start_date = datetime(year, month, 1)
        if month == 12:
            end_date = datetime(year + 1, 1, 1)
        else:
            end_date = datetime(year, month + 1, 1)
        
        attendance_records = await db.attendance.find({
            "child_id": child_id,
            "date": {"$gte": start_date.date(), "$lt": end_date.date()}
        }).to_list(1000)
        
        # Create calendar structure
        cal = calendar.monthcalendar(year, month)
        calendar_data = []
        
        for week in cal:
            week_data = []
            for day in week:
                if day == 0:
                    week_data.append({"day": 0, "status": None})
                else:
                    day_date = date(year, month, day)
                    # Find attendance for this day
                    day_attendance = next(
                        (a for a in attendance_records if a.get("date") == day_date),
                        None
                    )
                    week_data.append({
                        "day": day,
                        "date": day_date.isoformat(),
                        "status": day_attendance.get("status") if day_attendance else None,
                        "notes": day_attendance.get("coach_notes") if day_attendance else None
                    })
            calendar_data.append(week_data)
        
        return {
            "success": True,
            "calendar": calendar_data,
            "month": month,
            "year": year,
            "month_name": calendar.month_name[month]
        }
    
    except HTTPException as he:
        raise he
    except Exception as e:
        print(f"Error getting attendance calendar: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

# ==================== PROGRESS REPORTS ====================

@parent_features_router.get("/progress/{child_id}")
async def get_child_progress(
    child_id: str,
    current_user: dict = Depends(get_current_user)
):
    """Get progress reports and skill assessments for a child"""
    try:
        # Verify child belongs to parent
        child = await db.children.find_one({"id": child_id})
        if not child or child.get("parent_id") != current_user["sub"]:
            raise HTTPException(status_code=403, detail="Not authorized")
        
        # Get enrollment to find program
        enrollment = await db.enrollments.find_one({
            "child_id": child_id,
            "status": "active"
        })
        
        if not enrollment:
            return {
                "success": True,
                "message": "No active enrollment found",
                "progress": [],
                "skills": []
            }
        
        # Get skill progress
        skill_progress = await db.skills_progress.find({
            "child_id": child_id
        }).sort("updated_at", -1).to_list(100)
        
        # Get feedback/progress notes
        feedback = await db.feedback.find({
            "child_id": child_id
        }).sort("created_at", -1).to_list(100)
        
        # Calculate overall progress
        if skill_progress:
            total_skills = len(skill_progress)
            mastered = sum(1 for s in skill_progress if s.get("status") == "mastered")
            in_progress = sum(1 for s in skill_progress if s.get("status") == "in_progress")
            overall_progress = (mastered / total_skills * 100) if total_skills > 0 else 0
        else:
            overall_progress = 0
            mastered = 0
            in_progress = 0
        
        return {
            "success": True,
            "progress": {
                "overall_progress": round(overall_progress, 2),
                "skills_mastered": mastered,
                "skills_in_progress": in_progress,
                "total_skills": len(skill_progress)
            },
            "skills": [serialize_doc(s) for s in skill_progress],
            "feedback": [serialize_doc(f) for f in feedback]
        }
    
    except HTTPException as he:
        raise he
    except Exception as e:
        print(f"Error getting progress: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@parent_features_router.get("/progress/{child_id}/summary")
async def get_progress_summary(
    child_id: str,
    current_user: dict = Depends(get_current_user)
):
    """Get summarized progress report for sharing"""
    try:
        # Verify child belongs to parent
        child = await db.children.find_one({"id": child_id})
        if not child or child.get("parent_id") != current_user["sub"]:
            raise HTTPException(status_code=403, detail="Not authorized")
        
        # Get enrollment duration
        enrollment = await db.enrollments.find_one({
            "child_id": child_id,
            "status": "active"
        })
        
        if not enrollment:
            raise HTTPException(status_code=404, detail="No active enrollment")
        
        enrollment_start = enrollment.get("start_date")
        months_enrolled = ((datetime.utcnow().date() - enrollment_start).days // 30) if enrollment_start else 0
        
        # Get attendance stats
        attendance_records = await db.attendance.find({"child_id": child_id}).to_list(1000)
        total_classes = len(attendance_records)
        present_count = sum(1 for a in attendance_records if a.get("status") == "present")
        attendance_rate = (present_count / total_classes * 100) if total_classes > 0 else 0
        
        # Get skill progress
        skill_progress = await db.skills_progress.find({"child_id": child_id}).to_list(100)
        mastered = sum(1 for s in skill_progress if s.get("status") == "mastered")
        
        # Get recent feedback
        recent_feedback = await db.feedback.find({
            "child_id": child_id
        }).sort("created_at", -1).limit(3).to_list(3)
        
        return {
            "success": True,
            "summary": {
                "child_name": child.get("name"),
                "months_enrolled": months_enrolled,
                "attendance_rate": round(attendance_rate, 2),
                "skills_mastered": mastered,
                "total_skills": len(skill_progress),
                "recent_feedback": [serialize_doc(f) for f in recent_feedback],
                "generated_at": datetime.utcnow().isoformat()
            }
        }
    
    except HTTPException as he:
        raise he
    except Exception as e:
        print(f"Error generating progress summary: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

# ==================== LEAVE MANAGEMENT ====================

@parent_features_router.post("/leave/request")
async def request_leave(
    leave_data: LeaveRequest,
    current_user: dict = Depends(get_current_user)
):
    """Request leave for a child"""
    try:
        # Verify child belongs to parent
        child = await db.children.find_one({"id": leave_data.child_id})
        if not child or child.get("parent_id") != current_user["sub"]:
            raise HTTPException(status_code=403, detail="Not authorized")
        
        # Create leave request
        leave_doc = {
            "id": str(__import__('uuid').uuid4()),
            "child_id": leave_data.child_id,
            "parent_id": current_user["sub"],
            "start_date": leave_data.start_date,
            "end_date": leave_data.end_date,
            "reason": leave_data.reason,
            "status": "pending",
            "created_at": datetime.utcnow(),
            "updated_at": datetime.utcnow()
        }
        
        await db.leave_requests.insert_one(leave_doc)
        
        # Calculate affected classes
        enrollment = await db.enrollments.find_one({
            "child_id": leave_data.child_id,
            "status": "active"
        })
        
        if enrollment:
            class_doc = await db.classes.find_one({"id": enrollment.get("class_id")})
            # Calculate number of classes in date range (simplified)
            days_diff = (leave_data.end_date - leave_data.start_date).days + 1
            classes_affected = days_diff // 7 * 2  # Assuming 2 classes per week average
        else:
            classes_affected = 0
        
        return {
            "success": True,
            "message": "Leave request submitted successfully",
            "leave_id": leave_doc["id"],
            "classes_affected": classes_affected
        }
    
    except HTTPException as he:
        raise he
    except Exception as e:
        print(f"Error requesting leave: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@parent_features_router.get("/leave/list")
async def list_leave_requests(
    child_id: Optional[str] = None,
    current_user: dict = Depends(get_current_user)
):
    """List all leave requests for parent's children"""
    try:
        query = {"parent_id": current_user["sub"]}
        if child_id:
            query["child_id"] = child_id
        
        leave_requests = await db.leave_requests.find(query).sort("created_at", -1).to_list(100)
        
        # Enrich with child names
        for leave in leave_requests:
            child = await db.children.find_one({"id": leave.get("child_id")})
            if child:
                leave["child_name"] = child.get("name")
        
        return {
            "success": True,
            "leave_requests": [serialize_doc(l) for l in leave_requests]
        }
    
    except Exception as e:
        print(f"Error listing leave requests: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@parent_features_router.get("/leave/makeup-credits/{child_id}")
async def get_makeup_credits(
    child_id: str,
    current_user: dict = Depends(get_current_user)
):
    """Get remaining makeup class credits"""
    try:
        # Verify child belongs to parent
        child = await db.children.find_one({"id": child_id})
        if not child or child.get("parent_id") != current_user["sub"]:
            raise HTTPException(status_code=403, detail="Not authorized")
        
        # Get enrollment
        enrollment = await db.enrollments.find_one({
            "child_id": child_id,
            "status": "active"
        })
        
        if not enrollment:
            return {"success": True, "credits": 0, "used": 0}
        
        # Calculate credits
        # Approved leaves give makeup credits
        approved_leaves = await db.leave_requests.find({
            "child_id": child_id,
            "status": "approved"
        }).to_list(100)
        
        total_credits = 0
        for leave in approved_leaves:
            days = (leave.get("end_date") - leave.get("start_date")).days + 1
            total_credits += days // 7 * 2  # 2 classes per week avg
        
        # Count used makeup classes
        makeup_used = await db.attendance.count_documents({
            "child_id": child_id,
            "status": "makeup"
        })
        
        remaining = max(0, total_credits - makeup_used)
        
        return {
            "success": True,
            "total_credits": total_credits,
            "used": makeup_used,
            "remaining": remaining
        }
    
    except HTTPException as he:
        raise he
    except Exception as e:
        print(f"Error getting makeup credits: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

# ==================== TRIAL CLASS BOOKING ====================

@parent_features_router.post("/trial/book")
async def book_trial_class(
    trial_data: TrialBooking
):
    """Book a trial class (public endpoint, no auth required)"""
    try:
        # Check for existing trial booking
        existing = await db.trial_bookings.find_one({
            "parent_phone": trial_data.parent_phone,
            "status": {"$in": ["pending", "confirmed"]}
        })
        
        if existing:
            raise HTTPException(
                status_code=400,
                detail="You already have a pending trial booking. Please contact us for rescheduling."
            )
        
        # Create trial booking
        trial_doc = {
            "id": str(__import__('uuid').uuid4()),
            "child_name": trial_data.child_name,
            "child_age": trial_data.child_age,
            "parent_name": trial_data.parent_name,
            "parent_phone": trial_data.parent_phone,
            "parent_email": trial_data.parent_email,
            "preferred_date": trial_data.preferred_date,
            "preferred_time": trial_data.preferred_time,
            "center_id": trial_data.center_id,
            "program_id": trial_data.program_id,
            "status": "pending",
            "created_at": datetime.utcnow(),
            "updated_at": datetime.utcnow()
        }
        
        await db.trial_bookings.insert_one(trial_doc)
        
        # Get center details
        center = await db.locations.find_one({"id": trial_data.center_id})
        center_name = center.get("name") if center else "Tumble Gym"
        
        return {
            "success": True,
            "message": "Trial class booking submitted successfully!",
            "booking_id": trial_doc["id"],
            "center_name": center_name,
            "next_steps": "Our team will contact you within 24 hours to confirm your trial class"
        }
    
    except HTTPException as he:
        raise he
    except Exception as e:
        print(f"Error booking trial: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@parent_features_router.get("/trial/my-bookings")
async def get_my_trial_bookings(
    current_user: dict = Depends(get_current_user)
):
    """Get trial bookings for current user"""
    try:
        user = await db.users.find_one({"id": current_user["sub"]})
        if not user:
            raise HTTPException(status_code=404, detail="User not found")
        
        bookings = await db.trial_bookings.find({
            "parent_phone": user.get("phone")
        }).sort("created_at", -1).to_list(10)
        
        # Enrich with center names
        for booking in bookings:
            center = await db.locations.find_one({"id": booking.get("center_id")})
            if center:
                booking["center_name"] = center.get("name")
        
        return {
            "success": True,
            "bookings": [serialize_doc(b) for b in bookings]
        }
    
    except HTTPException as he:
        raise he
    except Exception as e:
        print(f"Error getting trial bookings: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

# ==================== CLASS RESCHEDULING ====================

@parent_features_router.post("/reschedule/request")
async def request_reschedule(
    reschedule_data: RescheduleRequest,
    current_user: dict = Depends(get_current_user)
):
    """Request to reschedule to a different class"""
    try:
        # Verify child belongs to parent
        child = await db.children.find_one({"id": reschedule_data.child_id})
        if not child or child.get("parent_id") != current_user["sub"]:
            raise HTTPException(status_code=403, detail="Not authorized")
        
        # Verify both classes exist
        current_class = await db.classes.find_one({"id": reschedule_data.current_class_id})
        new_class = await db.classes.find_one({"id": reschedule_data.new_class_id})
        
        if not current_class or not new_class:
            raise HTTPException(status_code=404, detail="Class not found")
        
        # Check if new class has capacity
        enrollments_count = await db.enrollments.count_documents({
            "class_id": reschedule_data.new_class_id,
            "status": "active"
        })
        
        if enrollments_count >= new_class.get("capacity", 20):
            raise HTTPException(status_code=400, detail="New class is at full capacity")
        
        # Create reschedule request
        reschedule_doc = {
            "id": str(__import__('uuid').uuid4()),
            "child_id": reschedule_data.child_id,
            "parent_id": current_user["sub"],
            "current_class_id": reschedule_data.current_class_id,
            "new_class_id": reschedule_data.new_class_id,
            "reason": reschedule_data.reason,
            "status": "pending",
            "created_at": datetime.utcnow(),
            "updated_at": datetime.utcnow()
        }
        
        await db.reschedule_requests.insert_one(reschedule_doc)
        
        return {
            "success": True,
            "message": "Reschedule request submitted successfully",
            "request_id": reschedule_doc["id"],
            "current_class": f"{current_class.get('day_of_week')} {current_class.get('start_time')}",
            "new_class": f"{new_class.get('day_of_week')} {new_class.get('start_time')}"
        }
    
    except HTTPException as he:
        raise he
    except Exception as e:
        print(f"Error requesting reschedule: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@parent_features_router.get("/reschedule/available-slots")
async def get_available_slots(
    child_id: str,
    current_user: dict = Depends(get_current_user)
):
    """Get available class slots for rescheduling"""
    try:
        # Verify child belongs to parent
        child = await db.children.find_one({"id": child_id})
        if not child or child.get("parent_id") != current_user["sub"]:
            raise HTTPException(status_code=403, detail="Not authorized")
        
        # Get child's current enrollment
        enrollment = await db.enrollments.find_one({
            "child_id": child_id,
            "status": "active"
        })
        
        if not enrollment:
            return {"success": True, "slots": []}
        
        # Get current class program
        current_class = await db.classes.find_one({"id": enrollment.get("class_id")})
        if not current_class:
            return {"success": True, "slots": []}
        
        # Find classes with same program and level
        available_classes = await db.classes.find({
            "program_id": current_class.get("program_id"),
            "location_id": current_class.get("location_id"),
            "id": {"$ne": current_class.get("id")}  # Exclude current class
        }).to_list(100)
        
        # Check capacity for each class
        slots = []
        for cls in available_classes:
            enrollments = await db.enrollments.count_documents({
                "class_id": cls["id"],
                "status": "active"
            })
            capacity = cls.get("capacity", 20)
            available_spots = capacity - enrollments
            
            if available_spots > 0:
                slots.append({
                    "class_id": cls["id"],
                    "day": cls.get("day_of_week"),
                    "time": cls.get("start_time"),
                    "duration": cls.get("duration"),
                    "coach_name": cls.get("coach_name"),
                    "available_spots": available_spots,
                    "capacity": capacity
                })
        
        return {
            "success": True,
            "slots": slots
        }
    
    except HTTPException as he:
        raise he
    except Exception as e:
        print(f"Error getting available slots: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

# ==================== EVENTS ====================

@parent_features_router.get("/events/upcoming")
async def get_upcoming_events(
    center_id: Optional[str] = None,
    current_user: dict = Depends(get_current_user)
):
    """Get upcoming events"""
    try:
        query = {
            "event_date": {"$gte": datetime.utcnow().date()},
            "status": "active"
        }
        
        if center_id:
            query["center_id"] = center_id
        
        events = await db.events.find(query).sort("event_date", 1).to_list(100)
        
        # Enrich with center names
        for event in events:
            center = await db.locations.find_one({"id": event.get("center_id")})
            if center:
                event["center_name"] = center.get("name")
        
        return {
            "success": True,
            "events": [serialize_doc(e) for e in events]
        }
    
    except Exception as e:
        print(f"Error getting events: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@parent_features_router.post("/events/{event_id}/register")
async def register_for_event(
    event_id: str,
    child_id: str,
    current_user: dict = Depends(get_current_user)
):
    """Register child for an event"""
    try:
        # Verify child belongs to parent
        child = await db.children.find_one({"id": child_id})
        if not child or child.get("parent_id") != current_user["sub"]:
            raise HTTPException(status_code=403, detail="Not authorized")
        
        # Check if event exists
        event = await db.events.find_one({"id": event_id})
        if not event:
            raise HTTPException(status_code=404, detail="Event not found")
        
        # Check if already registered
        existing = await db.event_registrations.find_one({
            "event_id": event_id,
            "child_id": child_id
        })
        
        if existing:
            raise HTTPException(status_code=400, detail="Already registered for this event")
        
        # Check capacity
        registrations = await db.event_registrations.count_documents({"event_id": event_id})
        if registrations >= event.get("capacity", 50):
            raise HTTPException(status_code=400, detail="Event is at full capacity")
        
        # Create registration
        registration_doc = {
            "id": str(__import__('uuid').uuid4()),
            "event_id": event_id,
            "child_id": child_id,
            "parent_id": current_user["sub"],
            "status": "confirmed",
            "registered_at": datetime.utcnow()
        }
        
        await db.event_registrations.insert_one(registration_doc)
        
        return {
            "success": True,
            "message": f"Successfully registered {child.get('name')} for {event.get('name')}",
            "registration_id": registration_doc["id"]
        }
    
    except HTTPException as he:
        raise he
    except Exception as e:
        print(f"Error registering for event: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@parent_features_router.get("/events/my-registrations")
async def get_my_event_registrations(
    current_user: dict = Depends(get_current_user)
):
    """Get all event registrations for parent's children"""
    try:
        registrations = await db.event_registrations.find({
            "parent_id": current_user["sub"]
        }).to_list(100)
        
        # Enrich with event and child details
        for reg in registrations:
            event = await db.events.find_one({"id": reg.get("event_id")})
            child = await db.children.find_one({"id": reg.get("child_id")})
            
            if event:
                reg["event_name"] = event.get("name")
                reg["event_date"] = event.get("event_date")
                reg["event_type"] = event.get("event_type")
            
            if child:
                reg["child_name"] = child.get("name")
        
        return {
            "success": True,
            "registrations": [serialize_doc(r) for r in registrations]
        }
    
    except Exception as e:
        print(f"Error getting registrations: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))
