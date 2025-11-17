"""
Curriculum & Skills Management Routes for Tumble Gym Coach App
"""

from fastapi import APIRouter, HTTPException, Depends
from motor.motor_asyncio import AsyncIOMotorClient
from dotenv import load_dotenv
from pathlib import Path
import os
from datetime import datetime, date
from typing import List, Optional
import uuid

from models import *
from auth import get_current_user

ROOT_DIR = Path(__file__).parent
load_dotenv(ROOT_DIR / '.env')

mongo_url = os.environ['MONGO_URL']
client = AsyncIOMotorClient(mongo_url)
db = client[os.environ['DB_NAME']]

curriculum_router = APIRouter(prefix="/api/curriculum", tags=["Curriculum"])
skills_router = APIRouter(prefix="/api/skills", tags=["Skills"])
feedback_router = APIRouter(prefix="/api/feedback", tags=["Feedback"])
coach_router = APIRouter(prefix="/api/coach", tags=["Coach Management"])

# ==================== CURRICULUM APIs ====================

@curriculum_router.get("/levels")
async def get_curriculum_levels(
    program: Optional[str] = None,
    current_user: dict = Depends(get_current_user)
):
    """Get all curriculum levels, optionally filtered by program"""
    query = {}
    if program:
        query["program"] = program
    
    levels = await db.curriculum_levels.find(query).sort("order", 1).to_list(100)
    return {"levels": levels, "total": len(levels)}

@curriculum_router.get("/levels/{level_id}")
async def get_level_details(
    level_id: str,
    current_user: dict = Depends(get_current_user)
):
    """Get level details"""
    level = await db.curriculum_levels.find_one({"id": level_id})
    if not level:
        raise HTTPException(status_code=404, detail="Level not found")
    return level

@curriculum_router.get("/levels/{level_id}/skills")
async def get_level_skills(
    level_id: str,
    category: Optional[str] = None,
    current_user: dict = Depends(get_current_user)
):
    """Get all skills for a curriculum level"""
    query = {"level_id": level_id}
    if category:
        query["category"] = category
    
    skills = await db.skills.find(query).sort("order", 1).to_list(200)
    return {"skills": skills, "total": len(skills)}

@curriculum_router.post("/levels")
async def create_curriculum_level(
    level_data: dict,
    current_user: dict = Depends(get_current_user)
):
    """Create new curriculum level (Admin only)"""
    if current_user.get("role") not in ["admin", "coach"]:
        raise HTTPException(status_code=403, detail="Not authorized")
    
    level = CurriculumLevel(**level_data)
    await db.curriculum_levels.insert_one(level.dict())
    return {"success": True, "level_id": level.id}

# ==================== SKILLS APIs ====================

@skills_router.post("/progress")
async def log_skill_progress(
    progress_data: dict,
    current_user: dict = Depends(get_current_user)
):
    """Log or update skill progress for a child"""
    if current_user.get("role") != "coach":
        raise HTTPException(status_code=403, detail="Only coaches can log progress")
    
    # Check if progress already exists
    existing = await db.skill_progress.find_one({
        "child_id": progress_data["child_id"],
        "skill_id": progress_data["skill_id"]
    })
    
    if existing:
        # Update existing progress
        await db.skill_progress.update_one(
            {"id": existing["id"]},
            {"$set": {
                "stage": progress_data.get("stage", existing["stage"]),
                "notes": progress_data.get("notes", existing.get("notes")),
                "media_url": progress_data.get("media_url", existing.get("media_url")),
                "coach_id": current_user["sub"],
                "updated_at": datetime.utcnow()
            }}
        )
        progress_id = existing["id"]
    else:
        # Create new progress entry
        progress = SkillProgress(
            child_id=progress_data["child_id"],
            skill_id=progress_data["skill_id"],
            stage=progress_data.get("stage", "attempted"),
            coach_id=current_user["sub"],
            notes=progress_data.get("notes"),
            media_url=progress_data.get("media_url")
        )
        await db.skill_progress.insert_one(progress.dict())
        progress_id = progress.id
    
    # Check if child earned any badges
    await check_and_award_badges(progress_data["child_id"])
    
    return {"success": True, "progress_id": progress_id}

@skills_router.get("/progress/{child_id}")
async def get_child_skill_progress(
    child_id: str,
    level_id: Optional[str] = None,
    current_user: dict = Depends(get_current_user)
):
    """Get all skill progress for a child"""
    query = {"child_id": child_id}
    progress_records = await db.skill_progress.find(query).to_list(1000)
    
    # Enrich with skill details
    enriched = []
    for record in progress_records:
        skill = await db.skills.find_one({"id": record["skill_id"]})
        if skill:
            if level_id and skill.get("level_id") != level_id:
                continue
            enriched.append({
                **record,
                "skill_name": skill.get("name"),
                "skill_category": skill.get("category"),
                "level_id": skill.get("level_id")
            })
    
    return {"progress": enriched, "total": len(enriched)}

@skills_router.get("/progress/{child_id}/summary")
async def get_progress_summary(
    child_id: str,
    current_user: dict = Depends(get_current_user)
):
    """Get progress summary with statistics"""
    progress_records = await db.skill_progress.find({"child_id": child_id}).to_list(1000)
    
    stats = {
        "total_skills": len(progress_records),
        "attempted": len([p for p in progress_records if p.get("stage") == "attempted"]),
        "assisted": len([p for p in progress_records if p.get("stage") == "assisted"]),
        "independent": len([p for p in progress_records if p.get("stage") == "independent"]),
        "mastered": len([p for p in progress_records if p.get("stage") == "mastered"])
    }
    
    # Get badges
    badges = await db.child_badges.find({"child_id": child_id}).to_list(100)
    badge_details = []
    for cb in badges:
        badge = await db.badges.find_one({"id": cb["badge_id"]})
        if badge:
            badge_details.append({
                **cb,
                "badge_name": badge.get("name"),
                "badge_icon": badge.get("icon")
            })
    
    return {
        "stats": stats,
        "badges": badge_details,
        "total_badges": len(badge_details)
    }

@skills_router.patch("/progress/{progress_id}")
async def update_skill_progress(
    progress_id: str,
    updates: dict,
    current_user: dict = Depends(get_current_user)
):
    """Update skill progress"""
    if current_user.get("role") != "coach":
        raise HTTPException(status_code=403, detail="Only coaches can update progress")
    
    updates["updated_at"] = datetime.utcnow()
    await db.skill_progress.update_one(
        {"id": progress_id},
        {"$set": updates}
    )
    return {"success": True}

# ==================== BADGES APIs ====================

@skills_router.get("/badges")
async def get_badges(
    level_id: Optional[str] = None,
    current_user: dict = Depends(get_current_user)
):
    """Get all available badges"""
    query = {}
    if level_id:
        query["level_id"] = level_id
    
    badges = await db.badges.find(query).to_list(100)
    return {"badges": badges, "total": len(badges)}

@skills_router.get("/badges/child/{child_id}")
async def get_child_badges(
    child_id: str,
    current_user: dict = Depends(get_current_user)
):
    """Get badges earned by child"""
    child_badges = await db.child_badges.find({"child_id": child_id}).to_list(100)
    
    # Enrich with badge details
    enriched = []
    for cb in child_badges:
        badge = await db.badges.find_one({"id": cb["badge_id"]})
        if badge:
            enriched.append({
                **cb,
                "badge_name": badge.get("name"),
                "badge_description": badge.get("description"),
                "badge_icon": badge.get("icon")
            })
    
    return {"badges": enriched, "total": len(enriched)}

async def check_and_award_badges(child_id: str):
    """Check if child qualifies for any new badges"""
    # Get all progress for child
    progress_records = await db.skill_progress.find({"child_id": child_id}).to_list(1000)
    
    # Get all badges
    all_badges = await db.badges.find({}).to_list(100)
    
    # Get already earned badges
    earned_badge_ids = [b["badge_id"] for b in await db.child_badges.find({"child_id": child_id}).to_list(100)]
    
    for badge in all_badges:
        if badge["id"] in earned_badge_ids:
            continue  # Already earned
        
        # Check criteria
        criteria = badge.get("criteria", {})
        skills_mastered = len([p for p in progress_records if p.get("stage") == "mastered"])
        
        if criteria.get("skills_mastered") and skills_mastered >= criteria["skills_mastered"]:
            # Award badge
            child_badge = ChildBadge(
                child_id=child_id,
                badge_id=badge["id"],
                awarded_by="system"
            )
            await db.child_badges.insert_one(child_badge.dict())

# ==================== FEEDBACK APIs ====================

@feedback_router.post("")
async def create_feedback(
    feedback_data: dict,
    current_user: dict = Depends(get_current_user)
):
    """Create feedback for a child"""
    if current_user.get("role") != "coach":
        raise HTTPException(status_code=403, detail="Only coaches can create feedback")
    
    feedback = Feedback(
        child_id=feedback_data["child_id"],
        coach_id=current_user["sub"],
        class_id=feedback_data.get("class_id"),
        period=feedback_data.get("period", "weekly"),
        strengths=feedback_data["strengths"],
        focus_areas=feedback_data["focus_areas"],
        next_goals=feedback_data["next_goals"],
        overall_rating=feedback_data.get("overall_rating", 3),
        media_urls=feedback_data.get("media_urls", [])
    )
    
    await db.feedback.insert_one(feedback.dict())
    return {"success": True, "feedback_id": feedback.id}

@feedback_router.get("/{child_id}")
async def get_child_feedback(
    child_id: str,
    status: Optional[str] = None,
    current_user: dict = Depends(get_current_user)
):
    """Get feedback for a child"""
    query = {"child_id": child_id}
    if status:
        query["status"] = status
    
    feedback_records = await db.feedback.find(query).sort("created_at", -1).to_list(100)
    
    # Enrich with coach details
    for fb in feedback_records:
        coach = await db.users.find_one({"id": fb["coach_id"]})
        if coach:
            fb["coach_name"] = coach.get("name")
    
    return {"feedback": feedback_records, "total": len(feedback_records)}

@feedback_router.patch("/{feedback_id}/submit")
async def submit_feedback(
    feedback_id: str,
    current_user: dict = Depends(get_current_user)
):
    """Submit feedback for approval"""
    if current_user.get("role") != "coach":
        raise HTTPException(status_code=403, detail="Only coaches can submit feedback")
    
    await db.feedback.update_one(
        {"id": feedback_id},
        {"$set": {"status": "submitted"}}
    )
    return {"success": True}

@feedback_router.patch("/{feedback_id}/approve")
async def approve_feedback(
    feedback_id: str,
    current_user: dict = Depends(get_current_user)
):
    """Approve feedback (Admin only)"""
    if current_user.get("role") not in ["admin", "franchise"]:
        raise HTTPException(status_code=403, detail="Only admins can approve feedback")
    
    await db.feedback.update_one(
        {"id": feedback_id},
        {"$set": {
            "status": "approved",
            "approved_by": current_user["sub"],
            "approved_at": datetime.utcnow()
        }}
    )
    return {"success": True}

# ==================== COACH MANAGEMENT APIs ====================

@coach_router.post("/checkin")
async def coach_checkin(
    checkin_data: dict,
    current_user: dict = Depends(get_current_user)
):
    """Coach daily check-in"""
    if current_user.get("role") != "coach":
        raise HTTPException(status_code=403, detail="Only coaches can check in")
    
    # Check if already checked in today
    today = datetime.utcnow().date()
    existing = await db.coach_checkins.find_one({
        "coach_id": current_user["sub"],
        "checkin_date": today
    })
    
    if existing:
        raise HTTPException(status_code=400, detail="Already checked in today")
    
    checkin = CoachCheckIn(
        coach_id=current_user["sub"],
        location_id=checkin_data["location_id"],
        notes=checkin_data.get("notes")
    )
    
    await db.coach_checkins.insert_one(checkin.dict())
    return {"success": True, "checkin_id": checkin.id}

@coach_router.post("/checkout")
async def coach_checkout(
    current_user: dict = Depends(get_current_user)
):
    """Coach daily check-out"""
    if current_user.get("role") != "coach":
        raise HTTPException(status_code=403, detail="Only coaches can check out")
    
    today = datetime.utcnow().date()
    checkin = await db.coach_checkins.find_one({
        "coach_id": current_user["sub"],
        "checkin_date": today
    })
    
    if not checkin:
        raise HTTPException(status_code=404, detail="No check-in found for today")
    
    await db.coach_checkins.update_one(
        {"id": checkin["id"]},
        {"$set": {"check_out_time": datetime.utcnow()}}
    )
    return {"success": True}

@coach_router.get("/attendance")
async def get_coach_attendance(
    current_user: dict = Depends(get_current_user)
):
    """Get coach attendance history"""
    if current_user.get("role") != "coach":
        raise HTTPException(status_code=403, detail="Not authorized")
    
    checkins = await db.coach_checkins.find({"coach_id": current_user["sub"]}).sort("date", -1).limit(30).to_list(30)
    return {"checkins": checkins, "total": len(checkins)}

@coach_router.post("/replacement-request")
async def request_replacement(
    request_data: dict,
    current_user: dict = Depends(get_current_user)
):
    """Request substitute coach"""
    if current_user.get("role") != "coach":
        raise HTTPException(status_code=403, detail="Only coaches can request replacements")
    
    replacement_request = ReplacementRequest(
        requester_coach_id=current_user["sub"],
        class_id=request_data["class_id"],
        request_date=request_data["date"],
        reason=request_data["reason"]
    )
    
    await db.replacement_requests.insert_one(replacement_request.dict())
    return {"success": True, "request_id": replacement_request.id}

@coach_router.get("/replacement-requests")
async def get_replacement_requests(
    current_user: dict = Depends(get_current_user)
):
    """Get replacement requests"""
    if current_user.get("role") == "coach":
        # Coaches see their own requests
        requests = await db.replacement_requests.find({"requester_coach_id": current_user["sub"]}).sort("created_at", -1).to_list(100)
    else:
        # Admins see all requests
        requests = await db.replacement_requests.find({}).sort("created_at", -1).to_list(100)
    
    return {"requests": requests, "total": len(requests)}

@coach_router.patch("/replacement/{request_id}")
async def update_replacement_request(
    request_id: str,
    updates: dict,
    current_user: dict = Depends(get_current_user)
):
    """Update replacement request status"""
    if current_user.get("role") not in ["admin", "franchise"]:
        raise HTTPException(status_code=403, detail="Only admins can update requests")
    
    if updates.get("status") in ["approved", "filled"]:
        updates["resolved_at"] = datetime.utcnow()
    
    await db.replacement_requests.update_one(
        {"id": request_id},
        {"$set": updates}
    )
    return {"success": True}
