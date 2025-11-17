"""
Curriculum & Weekly Schedule Routes
View weekly curriculum, lesson plans, and upcoming activities
"""
from fastapi import APIRouter, Depends, HTTPException, Query
from typing import Optional, List
from datetime import datetime, timedelta, date
from motor.motor_asyncio import AsyncIOMotorClient
from pathlib import Path
import os
from dotenv import load_dotenv

from auth import get_current_user

# Load environment variables
ROOT_DIR = Path(__file__).parent
load_dotenv(ROOT_DIR / '.env')

# MongoDB connection
mongo_url = os.environ['MONGO_URL']
client = AsyncIOMotorClient(mongo_url)
db = client[os.environ['DB_NAME']]

curriculum_weekly_router = APIRouter(prefix="/api/curriculum", tags=["Weekly Curriculum"])

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

# ==================== WEEKLY CURRICULUM ====================

@curriculum_weekly_router.get("/weekly/{child_id}")
async def get_weekly_curriculum(
    child_id: str,
    week_offset: int = Query(0, description="Weeks from current (0=current, 1=next, -1=previous)"),
    current_user: dict = Depends(get_current_user)
):
    """Get curriculum for a specific week for a child"""
    try:
        # Verify child belongs to parent
        child = await db.children.find_one({"id": child_id})
        if not child or child.get("parent_id") != current_user["sub"]:
            raise HTTPException(status_code=403, detail="Not authorized")
        
        # Get child's enrollment
        enrollment = await db.enrollments.find_one({
            "child_id": child_id,
            "status": "active"
        })
        
        if not enrollment:
            return {
                "success": True,
                "message": "No active enrollment",
                "curriculum": []
            }
        
        # Get program details
        program = await db.programs.find_one({"id": enrollment.get("program_id")})
        if not program:
            raise HTTPException(status_code=404, detail="Program not found")
        
        # Calculate week dates
        today = datetime.utcnow().date()
        week_start = today - timedelta(days=today.weekday()) + timedelta(weeks=week_offset)
        week_end = week_start + timedelta(days=6)
        
        # Get curriculum items for this week
        curriculum_items = await db.curriculum.find({
            "program_id": program["id"],
            "week_start_date": {"$gte": week_start, "$lte": week_end}
        }).sort("day_of_week", 1).to_list(100)
        
        # If no specific curriculum, get default program curriculum
        if not curriculum_items:
            curriculum_items = await db.program_curriculum.find({
                "program_id": program["id"]
            }).sort("week_number", 1).to_list(100)
        
        # Get class schedule for this week
        class_doc = await db.classes.find_one({"id": enrollment.get("class_id")})
        
        # Build weekly schedule
        weekly_schedule = []
        days = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday']
        
        for i, day in enumerate(days):
            day_date = week_start + timedelta(days=i)
            
            # Check if child has class on this day
            has_class = class_doc and class_doc.get("day_of_week") == day
            
            # Find curriculum for this day
            day_curriculum = next(
                (item for item in curriculum_items if item.get("day_of_week") == day),
                None
            )
            
            schedule_item = {
                "date": day_date.isoformat(),
                "day": day,
                "has_class": has_class,
                "class_time": f"{class_doc.get('start_time')} - {class_doc.get('end_time')}" if has_class else None,
                "curriculum": serialize_doc(day_curriculum) if day_curriculum else None
            }
            
            weekly_schedule.append(schedule_item)
        
        return {
            "success": True,
            "child_name": child.get("name"),
            "program_name": program.get("name"),
            "level": program.get("level"),
            "week_start": week_start.isoformat(),
            "week_end": week_end.isoformat(),
            "schedule": weekly_schedule
        }
    
    except HTTPException as he:
        raise he
    except Exception as e:
        print(f"Error getting weekly curriculum: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@curriculum_weekly_router.get("/lesson-plan/{curriculum_id}")
async def get_lesson_plan(
    curriculum_id: str,
    current_user: dict = Depends(get_current_user)
):
    """Get detailed lesson plan for a curriculum item"""
    try:
        curriculum = await db.curriculum.find_one({"id": curriculum_id})
        if not curriculum:
            raise HTTPException(status_code=404, detail="Curriculum not found")
        
        return {
            "success": True,
            "lesson_plan": serialize_doc(curriculum)
        }
    
    except HTTPException as he:
        raise he
    except Exception as e:
        print(f"Error getting lesson plan: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@curriculum_weekly_router.get("/upcoming-activities/{child_id}")
async def get_upcoming_activities(
    child_id: str,
    days: int = Query(7, le=30),
    current_user: dict = Depends(get_current_user)
):
    """Get upcoming activities and focus areas for a child"""
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
            return {"success": True, "activities": []}
        
        # Get upcoming curriculum items
        today = datetime.utcnow().date()
        end_date = today + timedelta(days=days)
        
        curriculum_items = await db.curriculum.find({
            "program_id": enrollment.get("program_id"),
            "week_start_date": {"$gte": today, "$lte": end_date}
        }).sort("week_start_date", 1).to_list(100)
        
        activities = []
        for item in curriculum_items:
            activities.append({
                "date": item.get("week_start_date"),
                "title": item.get("title"),
                "focus_area": item.get("focus_area"),
                "skills": item.get("skills", []),
                "description": item.get("description")
            })
        
        return {
            "success": True,
            "activities": [serialize_doc(a) for a in activities]
        }
    
    except HTTPException as he:
        raise he
    except Exception as e:
        print(f"Error getting activities: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@curriculum_weekly_router.get("/progress-tracking/{child_id}")
async def get_curriculum_progress(
    child_id: str,
    current_user: dict = Depends(get_current_user)
):
    """Track child's progress through curriculum"""
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
            return {"success": True, "progress": {}}
        
        # Get all curriculum items for program
        program_curriculum = await db.program_curriculum.find({
            "program_id": enrollment.get("program_id")
        }).to_list(100)
        
        # Get child's completed curriculum items
        completed_items = await db.curriculum_progress.find({
            "child_id": child_id
        }).to_list(1000)
        
        completed_ids = [item.get("curriculum_id") for item in completed_items]
        
        # Calculate progress
        total_items = len(program_curriculum)
        completed_count = len(completed_items)
        progress_percentage = (completed_count / total_items * 100) if total_items > 0 else 0
        
        # Group by skill categories
        skill_progress = {}
        for item in program_curriculum:
            skill_category = item.get("skill_category", "General")
            if skill_category not in skill_progress:
                skill_progress[skill_category] = {"total": 0, "completed": 0}
            
            skill_progress[skill_category]["total"] += 1
            if item.get("id") in completed_ids:
                skill_progress[skill_category]["completed"] += 1
        
        # Calculate percentage for each category
        for category in skill_progress:
            total = skill_progress[category]["total"]
            completed = skill_progress[category]["completed"]
            skill_progress[category]["percentage"] = (completed / total * 100) if total > 0 else 0
        
        return {
            "success": True,
            "progress": {
                "overall_percentage": round(progress_percentage, 2),
                "total_items": total_items,
                "completed_items": completed_count,
                "remaining_items": total_items - completed_count,
                "skill_progress": skill_progress
            }
        }
    
    except HTTPException as he:
        raise he
    except Exception as e:
        print(f"Error tracking curriculum progress: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))
