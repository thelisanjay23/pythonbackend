"""
Phase 2 & 3 Parent Features Routes
Photo Gallery, Achievements, Referrals, Health Info, Practice Resources, Community
"""
from fastapi import APIRouter, Depends, HTTPException, Query, UploadFile, File
from typing import Optional, List
from datetime import datetime
from pydantic import BaseModel
from motor.motor_asyncio import AsyncIOMotorClient
from pathlib import Path
import os
from dotenv import load_dotenv
import base64

from auth import get_current_user

# Load environment variables
ROOT_DIR = Path(__file__).parent
load_dotenv(ROOT_DIR / '.env')

# MongoDB connection
mongo_url = os.environ['MONGO_URL']
client = AsyncIOMotorClient(mongo_url)
db = client[os.environ['DB_NAME']]

phase2_router = APIRouter(prefix="/api/parent/features", tags=["Parent Features - Phase 2&3"])

# ==================== MODELS ====================

class ReferralCreate(BaseModel):
    referee_name: str
    referee_phone: str
    referee_email: Optional[str] = None
    relationship: Optional[str] = None

class HealthInfoUpdate(BaseModel):
    child_id: str
    medical_conditions: Optional[List[str]] = []
    allergies: Optional[List[str]] = []
    medications: Optional[List[str]] = []
    emergency_contact_name: str
    emergency_contact_phone: str
    emergency_contact_relationship: str
    doctor_name: Optional[str] = None
    doctor_phone: Optional[str] = None
    insurance_provider: Optional[str] = None
    insurance_number: Optional[str] = None

class CommunityPost(BaseModel):
    title: str
    content: str
    category: str  # question, tip, story, photo

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
    return doc

# ==================== PHOTO/VIDEO GALLERY ====================

@phase2_router.get("/gallery/{child_id}")
async def get_child_gallery(
    child_id: str,
    media_type: Optional[str] = Query(None, regex="^(photo|video|all)$"),
    month: Optional[int] = None,
    year: Optional[int] = None,
    current_user: dict = Depends(get_current_user)
):
    """Get photos and videos of a child from classes"""
    try:
        # Verify child belongs to parent
        child = await db.children.find_one({"id": child_id})
        if not child or child.get("parent_id") != current_user["sub"]:
            raise HTTPException(status_code=403, detail="Not authorized")
        
        # Build query
        query = {"child_id": child_id}
        
        if media_type and media_type != "all":
            query["media_type"] = media_type
        
        if month and year:
            start_date = datetime(year, month, 1)
            if month == 12:
                end_date = datetime(year + 1, 1, 1)
            else:
                end_date = datetime(year, month + 1, 1)
            query["created_at"] = {"$gte": start_date, "$lt": end_date}
        
        # Get media
        media_items = await db.gallery.find(query).sort("created_at", -1).to_list(200)
        
        # Enrich with class info
        for item in media_items:
            if item.get("class_id"):
                class_doc = await db.classes.find_one({"id": item["class_id"]})
                if class_doc:
                    item["class_name"] = f"{class_doc.get('day_of_week')} {class_doc.get('start_time')}"
        
        return {
            "success": True,
            "media": [serialize_doc(m) for m in media_items],
            "total": len(media_items)
        }
    
    except HTTPException as he:
        raise he
    except Exception as e:
        print(f"Error getting gallery: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@phase2_router.get("/gallery/{child_id}/highlights")
async def get_monthly_highlights(
    child_id: str,
    current_user: dict = Depends(get_current_user)
):
    """Get monthly highlights reel"""
    try:
        # Verify child belongs to parent
        child = await db.children.find_one({"id": child_id})
        if not child or child.get("parent_id") != current_user["sub"]:
            raise HTTPException(status_code=403, detail="Not authorized")
        
        # Get current month photos
        now = datetime.utcnow()
        start_date = datetime(now.year, now.month, 1)
        
        media_items = await db.gallery.find({
            "child_id": child_id,
            "created_at": {"$gte": start_date},
            "is_highlight": True
        }).sort("created_at", -1).to_list(10)
        
        return {
            "success": True,
            "highlights": [serialize_doc(m) for m in media_items],
            "month": now.strftime("%B %Y")
        }
    
    except HTTPException as he:
        raise he
    except Exception as e:
        print(f"Error getting highlights: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

# ==================== ACHIEVEMENTS & REWARDS ====================

@phase2_router.get("/achievements/{child_id}")
async def get_child_achievements(
    child_id: str,
    current_user: dict = Depends(get_current_user)
):
    """Get all achievements and badges for a child"""
    try:
        # Verify child belongs to parent
        child = await db.children.find_one({"id": child_id})
        if not child or child.get("parent_id") != current_user["sub"]:
            raise HTTPException(status_code=403, detail="Not authorized")
        
        # Get achievements
        achievements = await db.achievements.find({
            "child_id": child_id
        }).sort("earned_at", -1).to_list(100)
        
        # Get certificates
        certificates = await db.certificates.find({
            "child_id": child_id
        }).sort("issued_at", -1).to_list(50)
        
        # Calculate stats
        total_badges = len([a for a in achievements if a.get("type") == "badge"])
        total_certificates = len(certificates)
        total_points = sum(a.get("points", 0) for a in achievements)
        
        # Get recent achievements (last 30 days)
        thirty_days_ago = datetime.utcnow() - __import__('datetime').timedelta(days=30)
        recent = [a for a in achievements if a.get("earned_at", datetime.min) >= thirty_days_ago]
        
        return {
            "success": True,
            "achievements": [serialize_doc(a) for a in achievements],
            "certificates": [serialize_doc(c) for c in certificates],
            "stats": {
                "total_badges": total_badges,
                "total_certificates": total_certificates,
                "total_points": total_points,
                "recent_achievements": len(recent)
            }
        }
    
    except HTTPException as he:
        raise he
    except Exception as e:
        print(f"Error getting achievements: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@phase2_router.get("/achievements/{child_id}/leaderboard")
async def get_leaderboard(
    child_id: str,
    period: str = Query("month", regex="^(week|month|all)$"),
    current_user: dict = Depends(get_current_user)
):
    """Get leaderboard for child's program"""
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
            return {"success": True, "leaderboard": [], "child_rank": None}
        
        # Get all children in same program
        same_program_enrollments = await db.enrollments.find({
            "program_id": enrollment.get("program_id"),
            "status": "active"
        }).to_list(1000)
        
        child_ids = [e["child_id"] for e in same_program_enrollments]
        
        # Calculate points for each child
        leaderboard = []
        for cid in child_ids:
            achievements = await db.achievements.find({"child_id": cid}).to_list(1000)
            total_points = sum(a.get("points", 0) for a in achievements)
            
            child_info = await db.children.find_one({"id": cid})
            if child_info:
                leaderboard.append({
                    "child_id": cid,
                    "child_name": child_info.get("name"),
                    "points": total_points,
                    "badges": len([a for a in achievements if a.get("type") == "badge"])
                })
        
        # Sort by points
        leaderboard.sort(key=lambda x: x["points"], reverse=True)
        
        # Add ranks
        for idx, entry in enumerate(leaderboard):
            entry["rank"] = idx + 1
        
        # Find child's rank
        child_rank = next((e for e in leaderboard if e["child_id"] == child_id), None)
        
        return {
            "success": True,
            "leaderboard": leaderboard[:10],  # Top 10
            "child_rank": child_rank,
            "total_participants": len(leaderboard)
        }
    
    except HTTPException as he:
        raise he
    except Exception as e:
        print(f"Error getting leaderboard: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

# ==================== REFERRAL PROGRAM ====================

@phase2_router.post("/referral/create")
async def create_referral(
    referral_data: ReferralCreate,
    current_user: dict = Depends(get_current_user)
):
    """Create a new referral"""
    try:
        # Check if already referred
        existing = await db.referrals.find_one({
            "referee_phone": referral_data.referee_phone,
            "referrer_id": current_user["sub"]
        })
        
        if existing:
            raise HTTPException(status_code=400, detail="You have already referred this person")
        
        # Generate referral code
        import random
        import string
        referral_code = ''.join(random.choices(string.ascii_uppercase + string.digits, k=8))
        
        # Create referral
        referral_doc = {
            "id": str(__import__('uuid').uuid4()),
            "referrer_id": current_user["sub"],
            "referee_name": referral_data.referee_name,
            "referee_phone": referral_data.referee_phone,
            "referee_email": referral_data.referee_email,
            "relationship": referral_data.relationship,
            "referral_code": referral_code,
            "status": "pending",  # pending, enrolled, expired
            "reward_earned": False,
            "created_at": datetime.utcnow(),
            "updated_at": datetime.utcnow()
        }
        
        await db.referrals.insert_one(referral_doc)
        
        return {
            "success": True,
            "message": "Referral created successfully!",
            "referral_code": referral_code,
            "referral_id": referral_doc["id"]
        }
    
    except HTTPException as he:
        raise he
    except Exception as e:
        print(f"Error creating referral: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@phase2_router.get("/referral/my-referrals")
async def get_my_referrals(
    current_user: dict = Depends(get_current_user)
):
    """Get all referrals made by current user"""
    try:
        referrals = await db.referrals.find({
            "referrer_id": current_user["sub"]
        }).sort("created_at", -1).to_list(100)
        
        # Calculate stats
        total_referrals = len(referrals)
        successful = len([r for r in referrals if r.get("status") == "enrolled"])
        pending = len([r for r in referrals if r.get("status") == "pending"])
        rewards_earned = sum(r.get("reward_amount", 0) for r in referrals if r.get("reward_earned"))
        
        return {
            "success": True,
            "referrals": [serialize_doc(r) for r in referrals],
            "stats": {
                "total_referrals": total_referrals,
                "successful": successful,
                "pending": pending,
                "rewards_earned": rewards_earned
            }
        }
    
    except Exception as e:
        print(f"Error getting referrals: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@phase2_router.get("/referral/rewards")
async def get_referral_rewards(
    current_user: dict = Depends(get_current_user)
):
    """Get referral rewards information"""
    try:
        # Get successful referrals
        successful_referrals = await db.referrals.find({
            "referrer_id": current_user["sub"],
            "status": "enrolled"
        }).to_list(100)
        
        # Calculate rewards (₹1000 per successful referral)
        reward_per_referral = 1000
        total_earned = len(successful_referrals) * reward_per_referral
        
        # Get redeemed rewards
        redeemed = await db.reward_redemptions.find({
            "user_id": current_user["sub"]
        }).to_list(100)
        
        total_redeemed = sum(r.get("amount", 0) for r in redeemed)
        available_balance = total_earned - total_redeemed
        
        return {
            "success": True,
            "rewards": {
                "total_earned": total_earned,
                "total_redeemed": total_redeemed,
                "available_balance": available_balance,
                "successful_referrals": len(successful_referrals),
                "reward_per_referral": reward_per_referral
            },
            "redemption_history": [serialize_doc(r) for r in redeemed]
        }
    
    except Exception as e:
        print(f"Error getting rewards: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

# ==================== HEALTH & EMERGENCY INFO ====================

@phase2_router.get("/health/{child_id}")
async def get_health_info(
    child_id: str,
    current_user: dict = Depends(get_current_user)
):
    """Get health and emergency information for a child"""
    try:
        # Verify child belongs to parent
        child = await db.children.find_one({"id": child_id})
        if not child or child.get("parent_id") != current_user["sub"]:
            raise HTTPException(status_code=403, detail="Not authorized")
        
        # Get health info
        health_info = await db.health_info.find_one({"child_id": child_id})
        
        if not health_info:
            # Return default structure
            return {
                "success": True,
                "health_info": {
                    "child_id": child_id,
                    "medical_conditions": [],
                    "allergies": [],
                    "medications": [],
                    "emergency_contact_name": "",
                    "emergency_contact_phone": "",
                    "emergency_contact_relationship": ""
                }
            }
        
        return {
            "success": True,
            "health_info": serialize_doc(health_info)
        }
    
    except HTTPException as he:
        raise he
    except Exception as e:
        print(f"Error getting health info: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@phase2_router.post("/health/update")
async def update_health_info(
    health_data: HealthInfoUpdate,
    current_user: dict = Depends(get_current_user)
):
    """Update health and emergency information"""
    try:
        # Verify child belongs to parent
        child = await db.children.find_one({"id": health_data.child_id})
        if not child or child.get("parent_id") != current_user["sub"]:
            raise HTTPException(status_code=403, detail="Not authorized")
        
        # Check if health info exists
        existing = await db.health_info.find_one({"child_id": health_data.child_id})
        
        health_doc = health_data.dict()
        health_doc["updated_at"] = datetime.utcnow()
        
        if existing:
            # Update
            await db.health_info.update_one(
                {"child_id": health_data.child_id},
                {"$set": health_doc}
            )
        else:
            # Create
            health_doc["id"] = str(__import__('uuid').uuid4())
            health_doc["created_at"] = datetime.utcnow()
            await db.health_info.insert_one(health_doc)
        
        return {
            "success": True,
            "message": "Health information updated successfully"
        }
    
    except HTTPException as he:
        raise he
    except Exception as e:
        print(f"Error updating health info: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

# ==================== HOME PRACTICE RESOURCES ====================

@phase2_router.get("/practice-resources")
async def get_practice_resources(
    level: Optional[str] = None,
    category: Optional[str] = Query(None, regex="^(warmup|exercise|cooldown|safety)$"),
    current_user: dict = Depends(get_current_user)
):
    """Get home practice video tutorials and resources"""
    try:
        query = {"status": "active"}
        
        if level:
            query["level"] = level
        if category:
            query["category"] = category
        
        resources = await db.practice_resources.find(query).sort("order", 1).to_list(100)
        
        return {
            "success": True,
            "resources": [serialize_doc(r) for r in resources],
            "total": len(resources)
        }
    
    except Exception as e:
        print(f"Error getting practice resources: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@phase2_router.get("/practice-resources/{resource_id}")
async def get_resource_details(
    resource_id: str,
    current_user: dict = Depends(get_current_user)
):
    """Get detailed information about a practice resource"""
    try:
        resource = await db.practice_resources.find_one({"id": resource_id})
        if not resource:
            raise HTTPException(status_code=404, detail="Resource not found")
        
        # Increment view count
        await db.practice_resources.update_one(
            {"id": resource_id},
            {"$inc": {"views": 1}}
        )
        
        return {
            "success": True,
            "resource": serialize_doc(resource)
        }
    
    except HTTPException as he:
        raise he
    except Exception as e:
        print(f"Error getting resource details: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

# ==================== PARENT COMMUNITY ====================

@phase2_router.get("/community/posts")
async def get_community_posts(
    category: Optional[str] = None,
    limit: int = Query(50, le=100),
    current_user: dict = Depends(get_current_user)
):
    """Get community posts from parents"""
    try:
        query = {}
        if category:
            query["category"] = category
        
        posts = await db.community_posts.find(query).sort("created_at", -1).to_list(limit)
        
        # Enrich with author info and like counts
        for post in posts:
            author = await db.users.find_one({"id": post.get("author_id")})
            if author:
                post["author_name"] = author.get("name")
            
            # Get like count
            likes = await db.post_likes.count_documents({"post_id": post.get("id")})
            post["likes_count"] = likes
            
            # Get comment count
            comments = await db.post_comments.count_documents({"post_id": post.get("id")})
            post["comments_count"] = comments
            
            # Check if current user liked
            user_liked = await db.post_likes.find_one({
                "post_id": post.get("id"),
                "user_id": current_user["sub"]
            })
            post["liked_by_user"] = user_liked is not None
        
        return {
            "success": True,
            "posts": [serialize_doc(p) for p in posts]
        }
    
    except Exception as e:
        print(f"Error getting community posts: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@phase2_router.post("/community/posts")
async def create_community_post(
    post_data: CommunityPost,
    current_user: dict = Depends(get_current_user)
):
    """Create a new community post"""
    try:
        post_doc = {
            "id": str(__import__('uuid').uuid4()),
            "author_id": current_user["sub"],
            "title": post_data.title,
            "content": post_data.content,
            "category": post_data.category,
            "created_at": datetime.utcnow(),
            "updated_at": datetime.utcnow()
        }
        
        await db.community_posts.insert_one(post_doc)
        
        return {
            "success": True,
            "message": "Post created successfully",
            "post_id": post_doc["id"]
        }
    
    except Exception as e:
        print(f"Error creating post: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@phase2_router.post("/community/posts/{post_id}/like")
async def like_post(
    post_id: str,
    current_user: dict = Depends(get_current_user)
):
    """Like or unlike a post"""
    try:
        # Check if already liked
        existing = await db.post_likes.find_one({
            "post_id": post_id,
            "user_id": current_user["sub"]
        })
        
        if existing:
            # Unlike
            await db.post_likes.delete_one({"_id": existing["_id"]})
            return {"success": True, "liked": False}
        else:
            # Like
            like_doc = {
                "id": str(__import__('uuid').uuid4()),
                "post_id": post_id,
                "user_id": current_user["sub"],
                "created_at": datetime.utcnow()
            }
            await db.post_likes.insert_one(like_doc)
            return {"success": True, "liked": True}
    
    except Exception as e:
        print(f"Error liking post: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@phase2_router.get("/community/posts/{post_id}/comments")
async def get_post_comments(
    post_id: str,
    current_user: dict = Depends(get_current_user)
):
    """Get comments for a post"""
    try:
        comments = await db.post_comments.find({
            "post_id": post_id
        }).sort("created_at", 1).to_list(200)
        
        # Enrich with author info
        for comment in comments:
            author = await db.users.find_one({"id": comment.get("author_id")})
            if author:
                comment["author_name"] = author.get("name")
        
        return {
            "success": True,
            "comments": [serialize_doc(c) for c in comments]
        }
    
    except Exception as e:
        print(f"Error getting comments: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@phase2_router.post("/community/posts/{post_id}/comments")
async def create_comment(
    post_id: str,
    comment_text: str,
    current_user: dict = Depends(get_current_user)
):
    """Add a comment to a post"""
    try:
        comment_doc = {
            "id": str(__import__('uuid').uuid4()),
            "post_id": post_id,
            "author_id": current_user["sub"],
            "comment_text": comment_text,
            "created_at": datetime.utcnow()
        }
        
        await db.post_comments.insert_one(comment_doc)
        
        return {
            "success": True,
            "message": "Comment added successfully",
            "comment_id": comment_doc["id"]
        }
    
    except Exception as e:
        print(f"Error creating comment: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))
