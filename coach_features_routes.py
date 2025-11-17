"""
Coach Features Routes
Attendance marking, skill assessments, class notes, and geo-fencing
"""
from fastapi import APIRouter, Depends, HTTPException, Query
from typing import Optional, List
from datetime import datetime, date, timedelta
from pydantic import BaseModel
from motor.motor_asyncio import AsyncIOMotorClient
from pathlib import Path
import os
from dotenv import load_dotenv
import math

from auth import get_current_user

# Load environment variables
ROOT_DIR = Path(__file__).parent
load_dotenv(ROOT_DIR / '.env')

# MongoDB connection
mongo_url = os.environ['MONGO_URL']
client = AsyncIOMotorClient(mongo_url)
db = client[os.environ['DB_NAME']]

coach_router = APIRouter(prefix="/api/coach", tags=["Coach Features"])

# ==================== MODELS ====================

class AttendanceMarkRequest(BaseModel):
    class_id: str
    date: date
    students: List[dict]  # [{"child_id": "...", "status": "present/absent/late", "notes": "..."}]

class SkillAssessment(BaseModel):
    child_id: str
    skill_id: str
    skill_name: str
    status: str  # not_started, in_progress, mastered
    notes: Optional[str] = None
    assessment_date: date

class ClassNote(BaseModel):
    class_id: str
    date: date
    note_type: str  # general, observation, concern
    content: str
    students: Optional[List[str]] = []  # child_ids if student-specific

class GeofenceCheckIn(BaseModel):
    latitude: float
    longitude: float
    center_id: str

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

def calculate_distance(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Calculate distance between two coordinates in meters using Haversine formula"""
    R = 6371000  # Earth's radius in meters
    
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    delta_phi = math.radians(lat2 - lat1)
    delta_lambda = math.radians(lon2 - lon1)
    
    a = math.sin(delta_phi/2)**2 + math.cos(phi1) * math.cos(phi2) * math.sin(delta_lambda/2)**2
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1-a))
    
    distance = R * c
    return distance

# ==================== GEO-FENCING ====================

@coach_router.post("/geofence/check-in")
async def geofence_check_in(
    checkin_data: GeofenceCheckIn,
    current_user: dict = Depends(get_current_user)
):
    """Check if coach is within center's geofence and log attendance"""
    try:
        # Verify coach role
        if current_user.get("role") != "coach":
            raise HTTPException(status_code=403, detail="Only coaches can check in")
        
        # Get center location
        center = await db.locations.find_one({"id": checkin_data.center_id})
        if not center:
            raise HTTPException(status_code=404, detail="Center not found")
        
        # Calculate distance from center
        center_lat = center.get("lat")
        center_lng = center.get("lng")
        
        if not center_lat or not center_lng:
            raise HTTPException(status_code=400, detail="Center location not configured")
        
        distance = calculate_distance(
            checkin_data.latitude,
            checkin_data.longitude,
            center_lat,
            center_lng
        )
        
        # Geofence radius (default 100 meters)
        geofence_radius = center.get("geofence_radius", 100)
        
        within_geofence = distance <= geofence_radius
        
        # Log check-in attempt
        checkin_log = {
            "id": str(__import__('uuid').uuid4()),
            "coach_id": current_user["sub"],
            "center_id": checkin_data.center_id,
            "latitude": checkin_data.latitude,
            "longitude": checkin_data.longitude,
            "distance_from_center": round(distance, 2),
            "within_geofence": within_geofence,
            "timestamp": datetime.utcnow(),
            "check_type": "check_in"
        }
        
        await db.coach_checkins.insert_one(checkin_log)
        
        if not within_geofence:
            return {
                "success": False,
                "message": f"You are {round(distance)}m away from the center. Please be within {geofence_radius}m to check in.",
                "distance": round(distance, 2),
                "required_distance": geofence_radius,
                "within_geofence": False
            }
        
        # Update coach's active session
        today_start = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
        
        await db.coach_sessions.update_one(
            {
                "coach_id": current_user["sub"],
                "date": {"$gte": today_start, "$lt": today_start + timedelta(days=1)},
                "check_out_time": None
            },
            {
                "$set": {
                    "coach_id": current_user["sub"],
                    "center_id": checkin_data.center_id,
                    "date": datetime.utcnow(),
                    "check_in_time": datetime.utcnow(),
                    "check_in_location": {
                        "latitude": checkin_data.latitude,
                        "longitude": checkin_data.longitude
                    }
                }
            },
            upsert=True
        )
        
        return {
            "success": True,
            "message": "Successfully checked in!",
            "distance": round(distance, 2),
            "within_geofence": True,
            "check_in_time": datetime.utcnow().isoformat()
        }
    
    except HTTPException as he:
        raise he
    except Exception as e:
        print(f"Error in geofence check-in: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@coach_router.post("/geofence/check-out")
async def geofence_check_out(
    checkout_data: GeofenceCheckIn,
    current_user: dict = Depends(get_current_user)
):
    """Check out from center"""
    try:
        # Verify coach role
        if current_user.get("role") != "coach":
            raise HTTPException(status_code=403, detail="Only coaches can check out")
        
        # Get active session
        today_start = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
        
        session = await db.coach_sessions.find_one({
            "coach_id": current_user["sub"],
            "date": {"$gte": today_start, "$lt": today_start + timedelta(days=1)},
            "check_out_time": None
        })
        
        if not session:
            raise HTTPException(status_code=400, detail="No active check-in found")
        
        # Update session with check-out
        check_in_time = session.get("check_in_time")
        check_out_time = datetime.utcnow()
        
        duration_minutes = (check_out_time - check_in_time).total_seconds() / 60 if check_in_time else 0
        
        await db.coach_sessions.update_one(
            {"_id": session["_id"]},
            {
                "$set": {
                    "check_out_time": check_out_time,
                    "check_out_location": {
                        "latitude": checkout_data.latitude,
                        "longitude": checkout_data.longitude
                    },
                    "duration_minutes": round(duration_minutes, 2)
                }
            }
        )
        
        # Log check-out
        checkout_log = {
            "id": str(__import__('uuid').uuid4()),
            "coach_id": current_user["sub"],
            "center_id": checkout_data.center_id,
            "latitude": checkout_data.latitude,
            "longitude": checkout_data.longitude,
            "timestamp": check_out_time,
            "check_type": "check_out",
            "duration_minutes": round(duration_minutes, 2)
        }
        
        await db.coach_checkins.insert_one(checkout_log)
        
        return {
            "success": True,
            "message": "Successfully checked out!",
            "check_out_time": check_out_time.isoformat(),
            "duration_minutes": round(duration_minutes, 2),
            "duration_hours": round(duration_minutes / 60, 2)
        }
    
    except HTTPException as he:
        raise he
    except Exception as e:
        print(f"Error in check-out: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@coach_router.get("/geofence/status")
async def get_checkin_status(
    current_user: dict = Depends(get_current_user)
):
    """Get current check-in status"""
    try:
        # Get today's date range as datetime for MongoDB compatibility
        today_start = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
        today_end = today_start + timedelta(days=1)
        
        session = await db.coach_sessions.find_one({
            "coach_id": current_user["sub"],
            "date": {"$gte": today_start, "$lt": today_end},
            "check_out_time": None
        })
        
        if not session:
            return {
                "success": True,
                "checked_in": False,
                "message": "Not checked in"
            }
        
        check_in_time = session.get("check_in_time")
        duration_minutes = (datetime.utcnow() - check_in_time).total_seconds() / 60 if check_in_time else 0
        
        # Get center info
        center = await db.locations.find_one({"id": session.get("center_id")})
        
        return {
            "success": True,
            "checked_in": True,
            "session": {
                "center_name": center.get("name") if center else "Unknown",
                "center_id": session.get("center_id"),
                "check_in_time": check_in_time.isoformat() if check_in_time else None,
                "duration_minutes": round(duration_minutes, 2),
                "duration_hours": round(duration_minutes / 60, 2)
            }
        }
    
    except Exception as e:
        print(f"Error getting check-in status: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

# ==================== ATTENDANCE MARKING ====================

@coach_router.post("/attendance/mark")
async def mark_class_attendance(
    attendance_data: AttendanceMarkRequest,
    current_user: dict = Depends(get_current_user)
):
    """Mark attendance for a class"""
    try:
        # Verify coach role
        if current_user.get("role") != "coach":
            raise HTTPException(status_code=403, detail="Only coaches can mark attendance")
        
        # Verify coach teaches this class
        class_doc = await db.classes.find_one({"id": attendance_data.class_id})
        if not class_doc:
            raise HTTPException(status_code=404, detail="Class not found")
        
        if class_doc.get("coach_id") != current_user["sub"]:
            raise HTTPException(status_code=403, detail="You don't teach this class")
        
        # Mark attendance for each student
        marked_count = 0
        for student in attendance_data.students:
            attendance_record = {
                "id": str(__import__('uuid').uuid4()),
                "class_id": attendance_data.class_id,
                "child_id": student["child_id"],
                "date": attendance_data.date,
                "status": student["status"],
                "coach_notes": student.get("notes", ""),
                "marked_by": current_user["sub"],
                "created_at": datetime.utcnow(),
                "updated_at": datetime.utcnow()
            }
            
            # Upsert to avoid duplicates
            await db.attendance.update_one(
                {
                    "class_id": attendance_data.class_id,
                    "child_id": student["child_id"],
                    "date": attendance_data.date
                },
                {"$set": attendance_record},
                upsert=True
            )
            marked_count += 1
        
        return {
            "success": True,
            "message": f"Attendance marked for {marked_count} students",
            "marked_count": marked_count
        }
    
    except HTTPException as he:
        raise he
    except Exception as e:
        print(f"Error marking attendance: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@coach_router.get("/attendance/report")
async def get_attendance_report(
    class_id: Optional[str] = None,
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
    current_user: dict = Depends(get_current_user)
):
    """Get attendance report for coach's classes"""
    try:
        # Get coach's classes
        if class_id:
            classes = [await db.classes.find_one({"id": class_id, "coach_id": current_user["sub"]})]
            if not classes[0]:
                raise HTTPException(status_code=403, detail="Not your class")
        else:
            classes = await db.classes.find({"coach_id": current_user["sub"]}).to_list(100)
        
        class_ids = [c["id"] for c in classes if c]
        
        # Build query
        query = {"class_id": {"$in": class_ids}}
        
        if start_date and end_date:
            # Convert date objects to datetime for MongoDB compatibility
            start_datetime = datetime.combine(start_date, datetime.min.time()) if isinstance(start_date, date) else start_date
            end_datetime = datetime.combine(end_date, datetime.min.time()) if isinstance(end_date, date) else end_date
            query["date"] = {"$gte": start_datetime, "$lte": end_datetime}
        elif not start_date and not end_date:
            # Default to current month
            today = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
            start_of_month = today.replace(day=1)
            query["date"] = {"$gte": start_of_month}
        
        # Get attendance records
        attendance_records = await db.attendance.find(query).to_list(10000)
        
        # Calculate statistics
        total_records = len(attendance_records)
        present_count = sum(1 for r in attendance_records if r.get("status") == "present")
        absent_count = sum(1 for r in attendance_records if r.get("status") == "absent")
        late_count = sum(1 for r in attendance_records if r.get("status") == "late")
        
        attendance_rate = (present_count / total_records * 100) if total_records > 0 else 0
        
        return {
            "success": True,
            "statistics": {
                "total_records": total_records,
                "present": present_count,
                "absent": absent_count,
                "late": late_count,
                "attendance_rate": round(attendance_rate, 2)
            },
            "records": [serialize_doc(r) for r in attendance_records]
        }
    
    except HTTPException as he:
        raise he
    except Exception as e:
        print(f"Error getting attendance report: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

# ==================== SKILL ASSESSMENTS ====================

@coach_router.post("/skills/assess")
async def assess_student_skill(
    assessment: SkillAssessment,
    current_user: dict = Depends(get_current_user)
):
    """Assess a student's skill"""
    try:
        if current_user.get("role") != "coach":
            raise HTTPException(status_code=403, detail="Only coaches can assess skills")
        
        # Create or update assessment
        assessment_doc = {
            "id": str(__import__('uuid').uuid4()),
            "child_id": assessment.child_id,
            "skill_id": assessment.skill_id,
            "skill_name": assessment.skill_name,
            "status": assessment.status,
            "notes": assessment.notes,
            "assessment_date": datetime.combine(assessment.assessment_date, datetime.min.time()) if isinstance(assessment.assessment_date, date) else assessment.assessment_date,
            "assessed_by": current_user["sub"],
            "created_at": datetime.utcnow(),
            "updated_at": datetime.utcnow()
        }
        
        # Upsert
        await db.skills_progress.update_one(
            {
                "child_id": assessment.child_id,
                "skill_id": assessment.skill_id
            },
            {"$set": assessment_doc},
            upsert=True
        )
        
        return {
            "success": True,
            "message": "Skill assessment saved",
            "assessment_id": assessment_doc["id"]
        }
    
    except HTTPException as he:
        raise he
    except Exception as e:
        print(f"Error assessing skill: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@coach_router.get("/skills/my-students")
async def get_students_skill_progress(
    class_id: Optional[str] = None,
    current_user: dict = Depends(get_current_user)
):
    """Get skill progress for all students in coach's classes"""
    try:
        # Get coach's classes
        if class_id:
            classes = [await db.classes.find_one({"id": class_id, "coach_id": current_user["sub"]})]
        else:
            classes = await db.classes.find({"coach_id": current_user["sub"]}).to_list(100)
        
        # Get enrollments
        class_ids = [c["id"] for c in classes if c]
        enrollments = await db.enrollments.find({
            "class_id": {"$in": class_ids},
            "status": "active"
        }).to_list(1000)
        
        # Get students
        child_ids = [e["child_id"] for e in enrollments]
        
        students_progress = []
        for child_id in child_ids:
            child = await db.children.find_one({"id": child_id})
            if not child:
                continue
            
            # Get skill progress
            skills = await db.skills_progress.find({"child_id": child_id}).to_list(100)
            
            total_skills = len(skills)
            mastered = sum(1 for s in skills if s.get("status") == "mastered")
            in_progress = sum(1 for s in skills if s.get("status") == "in_progress")
            
            students_progress.append({
                "child_id": child_id,
                "child_name": child.get("name"),
                "total_skills": total_skills,
                "mastered": mastered,
                "in_progress": in_progress,
                "progress_percentage": (mastered / total_skills * 100) if total_skills > 0 else 0
            })
        
        return {
            "success": True,
            "students": students_progress
        }
    
    except Exception as e:
        print(f"Error getting students skill progress: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

# ==================== CLASS NOTES ====================

@coach_router.post("/notes/create")
async def create_class_note(
    note: ClassNote,
    current_user: dict = Depends(get_current_user)
):
    """Create a class note or observation"""
    try:
        if current_user.get("role") != "coach":
            raise HTTPException(status_code=403, detail="Only coaches can create notes")
        
        # Verify coach teaches this class
        class_doc = await db.classes.find_one({"id": note.class_id})
        if not class_doc or class_doc.get("coach_id") != current_user["sub"]:
            raise HTTPException(status_code=403, detail="Not your class")
        
        note_doc = {
            "id": str(__import__('uuid').uuid4()),
            "class_id": note.class_id,
            "date": datetime.combine(note.date, datetime.min.time()) if isinstance(note.date, date) else note.date,
            "note_type": note.note_type,
            "content": note.content,
            "students": note.students or [],
            "coach_id": current_user["sub"],
            "created_at": datetime.utcnow(),
            "updated_at": datetime.utcnow()
        }
        
        await db.class_notes.insert_one(note_doc)
        
        return {
            "success": True,
            "message": "Note created successfully",
            "note_id": note_doc["id"]
        }
    
    except HTTPException as he:
        raise he
    except Exception as e:
        print(f"Error creating class note: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@coach_router.get("/notes/list")
async def list_class_notes(
    class_id: Optional[str] = None,
    date: Optional[date] = None,
    current_user: dict = Depends(get_current_user)
):
    """List class notes"""
    try:
        query = {"coach_id": current_user["sub"]}
        
        if class_id:
            query["class_id"] = class_id
        if date:
            # Convert date to datetime for MongoDB compatibility
            query["date"] = datetime.combine(date, datetime.min.time()) if isinstance(date, date) else date
        
        notes = await db.class_notes.find(query).sort("created_at", -1).to_list(100)
        
        return {
            "success": True,
            "notes": [serialize_doc(n) for n in notes]
        }
    
    except Exception as e:
        print(f"Error listing notes: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

# ==================== COACH DASHBOARD ====================

@coach_router.get("/dashboard/today")
async def get_coach_dashboard(
    current_user: dict = Depends(get_current_user)
):
    """Get today's dashboard for coach"""
    try:
        today = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
        
        # Get coach's classes today
        classes_today = await db.classes.find({"coach_id": current_user["sub"]}).to_list(100)
        
        # Get students count
        class_ids = [c["id"] for c in classes_today]
        enrollments = await db.enrollments.find({
            "class_id": {"$in": class_ids},
            "status": "active"
        }).to_list(1000)
        
        # Check if attendance marked for today
        attendance_marked = await db.attendance.count_documents({
            "class_id": {"$in": class_ids},
            "date": today
        })
        
        # Get check-in status
        session = await db.coach_sessions.find_one({
            "coach_id": current_user["sub"],
            "date": today,
            "check_out_time": None
        })
        
        return {
            "success": True,
            "dashboard": {
                "classes_today": len(classes_today),
                "students_count": len(set([e["child_id"] for e in enrollments])),
                "attendance_marked": attendance_marked > 0,
                "checked_in": session is not None,
                "check_in_time": session.get("check_in_time").isoformat() if session and session.get("check_in_time") else None
            }
        }
    
    except Exception as e:
        print(f"Error getting dashboard: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))
