"""
Franchise Management Routes for Tumble Gym
Handle franchise owners, center managers, and access control
"""

from fastapi import APIRouter, HTTPException, Depends
from motor.motor_asyncio import AsyncIOMotorClient
from dotenv import load_dotenv
from pathlib import Path
import os
from datetime import datetime
import uuid
from typing import List, Optional

from models import *
from auth import get_current_user, get_password_hash

ROOT_DIR = Path(__file__).parent
load_dotenv(ROOT_DIR / '.env')

mongo_url = os.environ['MONGO_URL']
client = AsyncIOMotorClient(mongo_url)
db = client[os.environ['DB_NAME']]

franchise_router = APIRouter(prefix="/api/franchise", tags=["Franchise Management"])

# ==================== FRANCHISE USER MANAGEMENT ====================

@franchise_router.post("/users/create")
async def create_franchise_user(
    user_data: dict,
    current_user: dict = Depends(get_current_user)
):
    """
    Create franchise owner or center manager
    Only accessible by super admin
    """
    if current_user.get("role") != "admin":
        raise HTTPException(status_code=403, detail="Only super admin can create franchise users")
    
    # Check if user already exists
    existing = await db.users.find_one({"phone": user_data["phone"]})
    if existing:
        raise HTTPException(status_code=400, detail="User with this phone already exists")
    
    # Create new franchise user
    new_user = {
        "id": str(uuid.uuid4()),
        "phone": user_data["phone"],
        "email": user_data.get("email"),
        "name": user_data["name"],
        "role": user_data["role"],  # "franchise" or "manager"
        "password": get_password_hash(user_data["password"]),
        "assigned_locations": user_data.get("assigned_locations", []),  # List of location IDs
        "active": True,
        "created_at": datetime.utcnow(),
        "created_by": current_user["sub"],
        "referral_code": f"FR{user_data['phone'][-4:]}"
    }
    
    await db.users.insert_one(new_user)
    
    return {
        "success": True,
        "user_id": new_user["id"],
        "phone": new_user["phone"],
        "password": user_data["password"],  # Return for one-time viewing
        "role": new_user["role"]
    }

@franchise_router.get("/users")
async def get_franchise_users(
    role: Optional[str] = None,
    current_user: dict = Depends(get_current_user)
):
    """Get all franchise users"""
    if current_user.get("role") not in ["admin", "franchise"]:
        raise HTTPException(status_code=403, detail="Not authorized")
    
    query = {"role": {"$in": ["franchise", "manager"]}}
    if role:
        query["role"] = role
    
    users = await db.users.find(query).to_list(100)
    
    # Serialize and enrich with location details
    serialized_users = []
    for user in users:
        # Remove password
        user.pop("password", None)
        
        # Convert ObjectId to string
        if "_id" in user:
            user["_id"] = str(user["_id"])
        
        # Convert datetime to string
        if "created_at" in user and hasattr(user["created_at"], "isoformat"):
            user["created_at"] = user["created_at"].isoformat()
        
        # Add center count
        centers_count = await db.locations.count_documents({"franchise_owner_id": user.get("id")})
        user["centers_count"] = centers_count
        
        serialized_users.append(user)
    
    return {"users": serialized_users, "total": len(serialized_users)}

@franchise_router.get("/users/{user_id}")
async def get_franchise_user_details(
    user_id: str,
    current_user: dict = Depends(get_current_user)
):
    """Get detailed franchise user info"""
    if current_user.get("role") not in ["admin", "franchise"]:
        raise HTTPException(status_code=403, detail="Not authorized")
    
    user = await db.users.find_one({"id": user_id})
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    
    # Get assigned locations
    if user.get("assigned_locations"):
        locations = await db.locations.find({"id": {"$in": user["assigned_locations"]}}).to_list(100)
        user["locations"] = locations
    else:
        user["locations"] = []
    
    # Get stats
    if user.get("role") == "franchise":
        # Get all centers under franchise
        location_ids = user.get("assigned_locations", [])
        
        # Get classes
        classes = await db.classes.find({"location_id": {"$in": location_ids}}).to_list(1000)
        class_ids = [c["id"] for c in classes]
        
        # Get enrollments
        enrollments = await db.enrollments.count_documents({"class_id": {"$in": class_ids}, "status": "active"})
        
        # Get revenue
        enrollment_docs = await db.enrollments.find({"class_id": {"$in": class_ids}}).to_list(1000)
        enrollment_ids = [e["id"] for e in enrollment_docs]
        payments = await db.payments.find({"enrollment_id": {"$in": enrollment_ids}, "status": "success"}).to_list(1000)
        revenue = sum(p.get("total_amount", 0) for p in payments)
        
        user["stats"] = {
            "total_centers": len(location_ids),
            "total_classes": len(classes),
            "active_enrollments": enrollments,
            "total_revenue": revenue
        }
    
    user.pop("password", None)
    return user

@franchise_router.patch("/users/{user_id}")
async def update_franchise_user(
    user_id: str,
    updates: dict,
    current_user: dict = Depends(get_current_user)
):
    """Update franchise user"""
    if current_user.get("role") != "admin":
        raise HTTPException(status_code=403, detail="Only admin can update users")
    
    # Don't allow password update through this endpoint
    updates.pop("password", None)
    updates["updated_at"] = datetime.utcnow()
    
    await db.users.update_one(
        {"id": user_id},
        {"$set": updates}
    )
    return {"success": True}

@franchise_router.patch("/users/{user_id}/reset-password")
async def reset_user_password(
    user_id: str,
    new_password: str,
    current_user: dict = Depends(get_current_user)
):
    """Reset user password"""
    if current_user.get("role") != "admin":
        raise HTTPException(status_code=403, detail="Only admin can reset passwords")
    
    hashed_password = get_password_hash(new_password)
    
    await db.users.update_one(
        {"id": user_id},
        {"$set": {"password": hashed_password, "updated_at": datetime.utcnow()}}
    )
    
    return {
        "success": True,
        "message": "Password reset successfully",
        "new_password": new_password  # Return for one-time viewing
    }

@franchise_router.patch("/users/{user_id}/toggle-active")
async def toggle_user_active_status(
    user_id: str,
    current_user: dict = Depends(get_current_user)
):
    """Activate or deactivate user"""
    if current_user.get("role") != "admin":
        raise HTTPException(status_code=403, detail="Only admin can toggle user status")
    
    user = await db.users.find_one({"id": user_id})
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    
    new_status = not user.get("active", True)
    
    await db.users.update_one(
        {"id": user_id},
        {"$set": {"active": new_status, "updated_at": datetime.utcnow()}}
    )
    
    return {"success": True, "active": new_status}

# ==================== LOCATION ASSIGNMENT ====================

@franchise_router.post("/users/{user_id}/assign-locations")
async def assign_locations_to_user(
    user_id: str,
    location_ids: List[str],
    current_user: dict = Depends(get_current_user)
):
    """Assign locations to franchise owner or manager"""
    if current_user.get("role") != "admin":
        raise HTTPException(status_code=403, detail="Only admin can assign locations")
    
    # Verify locations exist
    locations = await db.locations.find({"id": {"$in": location_ids}}).to_list(100)
    if len(locations) != len(location_ids):
        raise HTTPException(status_code=404, detail="Some locations not found")
    
    await db.users.update_one(
        {"id": user_id},
        {"$set": {"assigned_locations": location_ids, "updated_at": datetime.utcnow()}}
    )
    
    return {"success": True, "assigned_count": len(location_ids)}

@franchise_router.delete("/users/{user_id}/remove-location/{location_id}")
async def remove_location_from_user(
    user_id: str,
    location_id: str,
    current_user: dict = Depends(get_current_user)
):
    """Remove location assignment"""
    if current_user.get("role") != "admin":
        raise HTTPException(status_code=403, detail="Only admin can remove locations")
    
    await db.users.update_one(
        {"id": user_id},
        {"$pull": {"assigned_locations": location_id}}
    )
    
    return {"success": True}

# ==================== FRANCHISE DASHBOARD ====================

@franchise_router.get("/dashboard")
async def get_franchise_dashboard(
    current_user: dict = Depends(get_current_user)
):
    """Get dashboard for franchise owner - SINGLE CENTER VIEW"""
    if current_user.get("role") not in ["franchise", "manager"]:
        raise HTTPException(status_code=403, detail="Only franchise users can access this")
    
    user = await db.users.find_one({"id": current_user["sub"]})
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    
    location_ids = user.get("assigned_locations", [])
    
    if not location_ids:
        return {
            "center": None,
            "stats": {},
            "recent_enrollments": [],
            "recent_payments": [],
            "attendance_trends": [],
            "top_programs": [],
            "revenue_breakdown": {},
            "message": "No center assigned"
        }
    
    # Get ONLY THE FIRST (PRIMARY) CENTER
    primary_location_id = location_ids[0]
    location = await db.locations.find_one({"id": primary_location_id})
    
    if not location:
        raise HTTPException(status_code=404, detail="Center not found")
    
    # Get classes for this center
    classes = await db.classes.find({"location_id": primary_location_id}).to_list(1000)
    class_ids = [c["id"] for c in classes]
    
    # Get enrollments
    enrollments_docs = await db.enrollments.find({"class_id": {"$in": class_ids}}).to_list(1000)
    active_enrollments = [e for e in enrollments_docs if e.get("status") == "active"]
    enrollment_ids = [e["id"] for e in enrollments_docs]
    
    # Get payments
    payments = await db.payments.find({"enrollment_id": {"$in": enrollment_ids}}).to_list(1000)
    successful_payments = [p for p in payments if p.get("status") == "success"]
    total_revenue = sum(p.get("total_amount", 0) for p in successful_payments)
    
    # Revenue breakdown by month (last 6 months)
    from collections import defaultdict
    monthly_revenue = defaultdict(float)
    for payment in successful_payments:
        if payment.get("created_at"):
            month_key = payment["created_at"].strftime("%Y-%m")
            monthly_revenue[month_key] += payment.get("total_amount", 0)
    
    # Get attendance data
    attendance = await db.attendance.find({"class_id": {"$in": class_ids}}).to_list(10000)
    total_attendance = len(attendance)
    present = len([a for a in attendance if a.get("status") == "present"])
    attendance_rate = (present / total_attendance * 100) if total_attendance > 0 else 0
    
    # Get coaches count
    coaches = await db.users.find({"role": "coach", "assigned_locations": primary_location_id}).to_list(100)
    
    # Determine center's primary brand based on classes offered
    center_brand = location.get("brand")  # Check if location has brand field
    if not center_brand and classes:
        # Determine brand from most common program brand in classes
        brand_counts = defaultdict(int)
        for class_doc in classes:
            program = await db.programs.find_one({"id": class_doc.get("program_id")})
            if program and program.get("brand"):
                brand_counts[program["brand"]] += 1
        if brand_counts:
            center_brand = max(brand_counts.items(), key=lambda x: x[1])[0]
    
    # Get program-wise enrollment count (FILTER BY CENTER'S BRAND)
    program_enrollments = defaultdict(int)
    for enrollment in active_enrollments:
        class_info = await db.classes.find_one({"id": enrollment.get("class_id")})
        if class_info:
            program = await db.programs.find_one({"id": class_info.get("program_id")})
            # Only include programs matching center's brand
            if program and (not center_brand or program.get("brand") == center_brand):
                program_name = class_info.get("program_name", "Unknown")
                program_enrollments[program_name] += 1
    
    top_programs = sorted(program_enrollments.items(), key=lambda x: x[1], reverse=True)[:5]
    
    # Recent enrollments (last 10)
    recent_enrollments = sorted(enrollments_docs, key=lambda x: x.get("created_at", datetime.min), reverse=True)[:10]
    recent_enrollments_data = []
    for enrollment in recent_enrollments:
        user_data = await db.users.find_one({"id": enrollment.get("user_id")})
        class_data = await db.classes.find_one({"id": enrollment.get("class_id")})
        recent_enrollments_data.append({
            "id": enrollment.get("id"),
            "user_name": user_data.get("name") if user_data else "Unknown",
            "class_name": class_data.get("program_name") if class_data else "Unknown",
            "status": enrollment.get("status"),
            "created_at": enrollment.get("created_at").isoformat() if enrollment.get("created_at") else None
        })
    
    # Recent payments (last 10)
    recent_payments_data = []
    recent_payments_sorted = sorted(payments, key=lambda x: x.get("created_at", datetime.min), reverse=True)[:10]
    for payment in recent_payments_sorted:
        user_data = await db.users.find_one({"id": payment.get("user_id")})
        recent_payments_data.append({
            "id": payment.get("id"),
            "user_name": user_data.get("name") if user_data else "Unknown",
            "amount": payment.get("total_amount", 0),
            "status": payment.get("status"),
            "method": payment.get("payment_method", "razorpay"),
            "created_at": payment.get("created_at").isoformat() if payment.get("created_at") else None
        })
    
    # Calculate occupancy rate (assuming capacity of 30 per class)
    total_capacity = len(classes) * 30
    occupancy_rate = (len(active_enrollments) / total_capacity * 100) if total_capacity > 0 else 0
    
    return {
        "center": {
            "id": location["id"],
            "name": location["name"],
            "city": location.get("city"),
            "address": location.get("address"),
            "phone": location.get("phone"),
        },
        "stats": {
            "total_members": len(active_enrollments),
            "total_classes": len(classes),
            "total_coaches": len(coaches),
            "total_revenue": total_revenue,
            "attendance_rate": round(attendance_rate, 2),
            "occupancy_rate": round(occupancy_rate, 2),
            "monthly_revenue": dict(monthly_revenue),
        },
        "recent_enrollments": recent_enrollments_data,
        "recent_payments": recent_payments_data,
        "top_programs": [{"program": prog, "count": count} for prog, count in top_programs],
        "revenue_breakdown": {
            "this_month": sum(p.get("total_amount", 0) for p in successful_payments if p.get("created_at") and p["created_at"].month == datetime.utcnow().month),
            "last_month": sum(p.get("total_amount", 0) for p in successful_payments if p.get("created_at") and p["created_at"].month == (datetime.utcnow().month - 1 if datetime.utcnow().month > 1 else 12)),
        }
    }
