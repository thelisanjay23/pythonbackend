"""
Centers Management Routes
Complete CRUD operations for gym centers/locations
"""
from fastapi import APIRouter, HTTPException, Depends, Query
from typing import Optional, List
from datetime import datetime
import os
from dotenv import load_dotenv
from motor.motor_asyncio import AsyncIOMotorClient
from pathlib import Path
import httpx

from auth import get_current_user
from models import Location, LocationBase

# Load environment variables
ROOT_DIR = Path(__file__).parent
load_dotenv(ROOT_DIR / '.env')

# MongoDB connection
mongo_url = os.environ['MONGO_URL']
client = AsyncIOMotorClient(mongo_url)
db = client[os.environ['DB_NAME']]

centers_router = APIRouter(prefix="/api/centers", tags=["Centers Management"])

# ==================== HELPER FUNCTIONS ====================

def serialize_center(center: dict) -> dict:
    """Convert MongoDB document to JSON-serializable dict"""
    if not center:
        return None
    if "_id" in center:
        del center["_id"]
    return center

async def fetch_google_place_details(place_id: str) -> dict:
    """Fetch place details from Google Places API"""
    try:
        api_key = os.getenv("GOOGLE_PLACES_API_KEY", "")
        if not api_key:
            return {"error": "Google Places API key not configured"}
        
        url = f"https://maps.googleapis.com/maps/api/place/details/json"
        params = {
            "place_id": place_id,
            "fields": "name,formatted_address,geometry,formatted_phone_number,website",
            "key": api_key
        }
        
        async with httpx.AsyncClient() as client:
            response = await client.get(url, params=params)
            data = response.json()
            
            if data.get("status") == "OK":
                result = data.get("result", {})
                return {
                    "name": result.get("name", ""),
                    "address": result.get("formatted_address", ""),
                    "lat": result.get("geometry", {}).get("location", {}).get("lat"),
                    "lng": result.get("geometry", {}).get("location", {}).get("lng"),
                    "phone": result.get("formatted_phone_number", ""),
                    "website": result.get("website", "")
                }
            else:
                return {"error": data.get("status")}
    except Exception as e:
        print(f"Error fetching Google Place details: {str(e)}")
        return {"error": str(e)}

async def search_google_places(query: str) -> List[dict]:
    """Search for places using Google Places API"""
    try:
        api_key = os.getenv("GOOGLE_PLACES_API_KEY", "")
        if not api_key:
            return []
        
        url = f"https://maps.googleapis.com/maps/api/place/textsearch/json"
        params = {
            "query": query,
            "key": api_key
        }
        
        async with httpx.AsyncClient() as client:
            response = await client.get(url, params=params)
            data = response.json()
            
            if data.get("status") == "OK":
                results = []
                for place in data.get("results", [])[:5]:  # Return top 5 results
                    results.append({
                        "place_id": place.get("place_id"),
                        "name": place.get("name"),
                        "address": place.get("formatted_address"),
                        "lat": place.get("geometry", {}).get("location", {}).get("lat"),
                        "lng": place.get("geometry", {}).get("location", {}).get("lng")
                    })
                return results
            else:
                return []
    except Exception as e:
        print(f"Error searching Google Places: {str(e)}")
        return []

# ==================== CENTER CRUD ENDPOINTS ====================

@centers_router.get("/list")
async def list_centers(
    city: Optional[str] = None,
    status: Optional[str] = None,
    search: Optional[str] = None,
    current_user: dict = Depends(get_current_user)
):
    """List all centers with optional filters"""
    try:
        query = {}
        
        # Apply filters
        if city:
            query["city"] = {"$regex": city, "$options": "i"}
        if status:
            query["status"] = status
        if search:
            query["$or"] = [
                {"name": {"$regex": search, "$options": "i"}},
                {"city": {"$regex": search, "$options": "i"}},
                {"address": {"$regex": search, "$options": "i"}}
            ]
        
        centers = await db.locations.find(query).to_list(100)
        
        # Enrich with stats
        for center in centers:
            center_id = center.get("id")
            
            # Count members (enrollments at this center)
            enrollments = await db.enrollments.count_documents({"center_id": center_id, "status": "active"})
            center["members_count"] = enrollments
            
            # Count classes
            classes_count = await db.classes.count_documents({"location_id": center_id})
            center["classes_count"] = classes_count
            
            # Count coaches assigned to this center
            coaches_count = len(set([
                cls["coach_id"] for cls in await db.classes.find({"location_id": center_id}).to_list(100)
            ]))
            center["coaches_count"] = coaches_count
            
            # Calculate revenue (sum of payments for enrollments at this center)
            enrollments_list = await db.enrollments.find({"center_id": center_id}).to_list(1000)
            enrollment_ids = [e["id"] for e in enrollments_list]
            payments = await db.payments.find({"enrollment_id": {"$in": enrollment_ids}, "status": "success"}).to_list(1000)
            center["revenue"] = sum(p.get("total_amount", 0) for p in payments)
            
            # Calculate capacity utilization (mock for now)
            center["capacity_utilization"] = min(int((enrollments / max(classes_count * 20, 1)) * 100), 100) if classes_count > 0 else 0
        
        return {
            "success": True,
            "centers": [serialize_center(c) for c in centers],
            "total": len(centers)
        }
    
    except Exception as e:
        print(f"Error listing centers: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@centers_router.get("/{center_id}")
async def get_center_details(
    center_id: str,
    current_user: dict = Depends(get_current_user)
):
    """Get detailed information about a specific center"""
    try:
        center = await db.locations.find_one({"id": center_id})
        if not center:
            raise HTTPException(status_code=404, detail="Center not found")
        
        # Get detailed stats
        enrollments = await db.enrollments.count_documents({"center_id": center_id, "status": "active"})
        classes = await db.classes.find({"location_id": center_id}).to_list(100)
        coaches = list(set([cls["coach_id"] for cls in classes]))
        
        # Get revenue data
        enrollments_list = await db.enrollments.find({"center_id": center_id}).to_list(1000)
        enrollment_ids = [e["id"] for e in enrollments_list]
        payments = await db.payments.find({"enrollment_id": {"$in": enrollment_ids}, "status": "success"}).to_list(1000)
        total_revenue = sum(p.get("total_amount", 0) for p in payments)
        
        # Get attendance data
        attendance_records = await db.attendance.find({
            "class_id": {"$in": [c["id"] for c in classes]}
        }).to_list(1000)
        present_count = sum(1 for a in attendance_records if a.get("status") == "present")
        attendance_rate = (present_count / len(attendance_records) * 100) if attendance_records else 0
        
        return {
            "success": True,
            "center": serialize_center(center),
            "stats": {
                "members_count": enrollments,
                "classes_count": len(classes),
                "coaches_count": len(coaches),
                "revenue": total_revenue,
                "attendance_rate": round(attendance_rate, 2)
            }
        }
    
    except HTTPException as he:
        raise he
    except Exception as e:
        print(f"Error getting center details: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@centers_router.post("/create")
async def create_center(
    center_data: LocationBase,
    current_user: dict = Depends(get_current_user)
):
    """Create a new center/location"""
    try:
        # Check authorization
        if current_user.get("role") not in ["admin", "franchise"]:
            raise HTTPException(status_code=403, detail="Not authorized to create centers")
        
        # Check for duplicate
        existing = await db.locations.find_one({"name": center_data.name, "city": center_data.city})
        if existing:
            raise HTTPException(status_code=400, detail="A center with this name already exists in this city")
        
        # Create center
        new_center = Location(**center_data.dict())
        center_dict = new_center.dict()
        center_dict["status"] = "active"
        center_dict["created_by"] = current_user["sub"]
        
        await db.locations.insert_one(center_dict)
        
        return {
            "success": True,
            "message": "Center created successfully",
            "center": serialize_center(center_dict)
        }
    
    except HTTPException as he:
        raise he
    except Exception as e:
        print(f"Error creating center: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@centers_router.patch("/{center_id}")
async def update_center(
    center_id: str,
    update_data: dict,
    current_user: dict = Depends(get_current_user)
):
    """Update center details"""
    try:
        # Check authorization
        if current_user.get("role") not in ["admin", "franchise"]:
            raise HTTPException(status_code=403, detail="Not authorized to update centers")
        
        # Check if center exists
        center = await db.locations.find_one({"id": center_id})
        if not center:
            raise HTTPException(status_code=404, detail="Center not found")
        
        # Update center
        allowed_fields = ["name", "city", "address", "lat", "lng", "phone", "whatsapp", "gstin", "status"]
        update_fields = {k: v for k, v in update_data.items() if k in allowed_fields}
        
        if not update_fields:
            raise HTTPException(status_code=400, detail="No valid fields to update")
        
        update_fields["updated_at"] = datetime.utcnow()
        update_fields["updated_by"] = current_user["sub"]
        
        await db.locations.update_one(
            {"id": center_id},
            {"$set": update_fields}
        )
        
        # Get updated center
        updated_center = await db.locations.find_one({"id": center_id})
        
        return {
            "success": True,
            "message": "Center updated successfully",
            "center": serialize_center(updated_center)
        }
    
    except HTTPException as he:
        raise he
    except Exception as e:
        print(f"Error updating center: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@centers_router.delete("/{center_id}")
async def delete_center(
    center_id: str,
    current_user: dict = Depends(get_current_user)
):
    """Delete/deactivate a center"""
    try:
        # Check authorization
        if current_user.get("role") not in ["admin"]:
            raise HTTPException(status_code=403, detail="Only admins can delete centers")
        
        # Check if center exists
        center = await db.locations.find_one({"id": center_id})
        if not center:
            raise HTTPException(status_code=404, detail="Center not found")
        
        # Check if center has active enrollments
        active_enrollments = await db.enrollments.count_documents({"center_id": center_id, "status": "active"})
        if active_enrollments > 0:
            raise HTTPException(
                status_code=400, 
                detail=f"Cannot delete center with {active_enrollments} active enrollments. Please deactivate instead."
            )
        
        # Soft delete by marking as inactive
        await db.locations.update_one(
            {"id": center_id},
            {"$set": {"status": "inactive", "deleted_at": datetime.utcnow(), "deleted_by": current_user["sub"]}}
        )
        
        return {
            "success": True,
            "message": "Center deactivated successfully"
        }
    
    except HTTPException as he:
        raise he
    except Exception as e:
        print(f"Error deleting center: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

# ==================== GOOGLE PLACES INTEGRATION ====================

@centers_router.get("/google-places/search")
async def search_places(
    query: str = Query(..., description="Search query for places"),
    current_user: dict = Depends(get_current_user)
):
    """Search for places using Google Places API"""
    try:
        if current_user.get("role") not in ["admin", "franchise"]:
            raise HTTPException(status_code=403, detail="Not authorized")
        
        results = await search_google_places(query)
        return {
            "success": True,
            "places": results
        }
    
    except HTTPException as he:
        raise he
    except Exception as e:
        print(f"Error searching places: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@centers_router.get("/google-places/details/{place_id}")
async def get_place_details(
    place_id: str,
    current_user: dict = Depends(get_current_user)
):
    """Get detailed information about a place from Google Places API"""
    try:
        if current_user.get("role") not in ["admin", "franchise"]:
            raise HTTPException(status_code=403, detail="Not authorized")
        
        details = await fetch_google_place_details(place_id)
        
        if "error" in details:
            raise HTTPException(status_code=400, detail=details["error"])
        
        return {
            "success": True,
            "place": details
        }
    
    except HTTPException as he:
        raise he
    except Exception as e:
        print(f"Error fetching place details: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

# ==================== CENTER STATISTICS ====================

@centers_router.get("/{center_id}/statistics")
async def get_center_statistics(
    center_id: str,
    period: str = Query("month", regex="^(week|month|quarter|year)$"),
    current_user: dict = Depends(get_current_user)
):
    """Get detailed statistics for a center"""
    try:
        center = await db.locations.find_one({"id": center_id})
        if not center:
            raise HTTPException(status_code=404, detail="Center not found")
        
        # Calculate date range based on period
        from datetime import timedelta
        end_date = datetime.utcnow()
        if period == "week":
            start_date = end_date - timedelta(days=7)
        elif period == "month":
            start_date = end_date - timedelta(days=30)
        elif period == "quarter":
            start_date = end_date - timedelta(days=90)
        else:  # year
            start_date = end_date - timedelta(days=365)
        
        # Get enrollments
        all_enrollments = await db.enrollments.find({"center_id": center_id}).to_list(1000)
        active_enrollments = [e for e in all_enrollments if e.get("status") == "active"]
        new_enrollments = [e for e in all_enrollments if e.get("created_at", datetime.min) >= start_date]
        
        # Get revenue
        enrollment_ids = [e["id"] for e in all_enrollments]
        payments = await db.payments.find({
            "enrollment_id": {"$in": enrollment_ids},
            "status": "success"
        }).to_list(1000)
        period_payments = [p for p in payments if p.get("created_at", datetime.min) >= start_date]
        total_revenue = sum(p.get("total_amount", 0) for p in payments)
        period_revenue = sum(p.get("total_amount", 0) for p in period_payments)
        
        # Get classes and attendance
        classes = await db.classes.find({"location_id": center_id}).to_list(100)
        class_ids = [c["id"] for c in classes]
        attendance_records = await db.attendance.find({"class_id": {"$in": class_ids}}).to_list(5000)
        period_attendance = [a for a in attendance_records if a.get("created_at", datetime.min) >= start_date]
        
        present_count = sum(1 for a in period_attendance if a.get("status") == "present")
        attendance_rate = (present_count / len(period_attendance) * 100) if period_attendance else 0
        
        # Get coaches
        coaches = list(set([c["coach_id"] for c in classes]))
        
        return {
            "success": True,
            "center_id": center_id,
            "center_name": center.get("name"),
            "period": period,
            "statistics": {
                "enrollments": {
                    "total": len(all_enrollments),
                    "active": len(active_enrollments),
                    "new_in_period": len(new_enrollments)
                },
                "revenue": {
                    "total": total_revenue,
                    "period": period_revenue,
                    "average_per_member": total_revenue / len(active_enrollments) if active_enrollments else 0
                },
                "attendance": {
                    "total_sessions": len(period_attendance),
                    "attended": present_count,
                    "rate_percentage": round(attendance_rate, 2)
                },
                "classes": len(classes),
                "coaches": len(coaches),
                "capacity_utilization": min(int((len(active_enrollments) / max(len(classes) * 20, 1)) * 100), 100)
            }
        }
    
    except HTTPException as he:
        raise he
    except Exception as e:
        print(f"Error fetching center statistics: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))
