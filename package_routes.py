"""
Package Management Routes for Tumble Gym
Handles membership package creation and management
"""
from fastapi import APIRouter, Depends, HTTPException, Query
from typing import Optional, List
from datetime import datetime
from pydantic import BaseModel
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

package_router = APIRouter(prefix="/api/packages", tags=["packages"])

# Models
class PackageCreate(BaseModel):
    name: str
    description: Optional[str] = None
    duration_months: int
    price: float
    brand: str  # tumble_gym, tumble_fit, tumble_gold
    features: List[str] = []
    is_active: bool = True

class PackageUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    duration_months: Optional[int] = None
    price: Optional[float] = None
    brand: Optional[str] = None
    features: Optional[List[str]] = None
    is_active: Optional[bool] = None

# Helper function to serialize package
def serialize_package(package: dict) -> dict:
    if "_id" in package:
        package["_id"] = str(package["_id"])
    if "created_at" in package and hasattr(package["created_at"], "isoformat"):
        package["created_at"] = package["created_at"].isoformat()
    if "updated_at" in package and hasattr(package["updated_at"], "isoformat"):
        package["updated_at"] = package["updated_at"].isoformat()
    return package

@package_router.get("")
async def get_packages(
    brand: Optional[str] = None,
    is_active: Optional[bool] = None,
    current_user: dict = Depends(get_current_user)
):
    """Get all packages (filtered by franchise owner if applicable)"""
    query = {}
    
    # Filter by brand if specified
    if brand:
        query["brand"] = brand
    
    # Filter by active status if specified
    if is_active is not None:
        query["is_active"] = is_active
    
    # Filter by franchise owner
    if current_user.get("role") == "franchise":
        query["created_by"] = current_user.get("id")
    elif current_user.get("role") == "manager":
        # Managers see packages from their center
        manager_center = await db.locations.find_one({"manager_id": current_user.get("id")})
        if manager_center:
            query["created_by"] = manager_center.get("franchise_owner_id")
    
    packages = await db.packages.find(query).to_list(100)
    
    # Serialize packages
    serialized_packages = [serialize_package(pkg) for pkg in packages]
    
    return {"packages": serialized_packages, "total": len(serialized_packages)}

@package_router.post("")
async def create_package(
    package: PackageCreate,
    current_user: dict = Depends(get_current_user)
):
    """Create a new package"""
    if current_user.get("role") not in ["admin", "franchise"]:
        raise HTTPException(status_code=403, detail="Not authorized to create packages")
    
    # Create package document
    package_doc = {
        "id": str(__import__('uuid').uuid4()),
        "name": package.name,
        "description": package.description,
        "duration_months": package.duration_months,
        "price": package.price,
        "brand": package.brand,
        "features": package.features,
        "is_active": package.is_active,
        "created_by": current_user.get("id"),
        "created_at": datetime.utcnow(),
        "updated_at": datetime.utcnow(),
    }
    
    await db.packages.insert_one(package_doc)
    
    return {"success": True, "package_id": package_doc["id"], "message": "Package created successfully"}

@package_router.get("/{package_id}")
async def get_package(
    package_id: str,
    current_user: dict = Depends(get_current_user)
):
    """Get a specific package"""
    package = await db.packages.find_one({"id": package_id})
    
    if not package:
        raise HTTPException(status_code=404, detail="Package not found")
    
    # Check access
    if current_user.get("role") == "franchise" and package.get("created_by") != current_user.get("id"):
        raise HTTPException(status_code=403, detail="Not authorized")
    
    return serialize_package(package)

@package_router.patch("/{package_id}")
async def update_package(
    package_id: str,
    update_data: PackageUpdate,
    current_user: dict = Depends(get_current_user)
):
    """Update a package"""
    package = await db.packages.find_one({"id": package_id})
    
    if not package:
        raise HTTPException(status_code=404, detail="Package not found")
    
    # Check authorization
    if current_user.get("role") == "franchise" and package.get("created_by") != current_user.get("id"):
        raise HTTPException(status_code=403, detail="Not authorized")
    
    if current_user.get("role") not in ["admin", "franchise"]:
        raise HTTPException(status_code=403, detail="Not authorized")
    
    # Build update dict
    update_dict = {"updated_at": datetime.utcnow()}
    
    if update_data.name is not None:
        update_dict["name"] = update_data.name
    if update_data.description is not None:
        update_dict["description"] = update_data.description
    if update_data.duration_months is not None:
        update_dict["duration_months"] = update_data.duration_months
    if update_data.price is not None:
        update_dict["price"] = update_data.price
    if update_data.brand is not None:
        update_dict["brand"] = update_data.brand
    if update_data.features is not None:
        update_dict["features"] = update_data.features
    if update_data.is_active is not None:
        update_dict["is_active"] = update_data.is_active
    
    await db.packages.update_one(
        {"id": package_id},
        {"$set": update_dict}
    )
    
    return {"success": True, "message": "Package updated successfully"}

@package_router.delete("/{package_id}")
async def delete_package(
    package_id: str,
    current_user: dict = Depends(get_current_user)
):
    """Delete a package"""
    package = await db.packages.find_one({"id": package_id})
    
    if not package:
        raise HTTPException(status_code=404, detail="Package not found")
    
    # Check authorization
    if current_user.get("role") == "franchise" and package.get("created_by") != current_user.get("id"):
        raise HTTPException(status_code=403, detail="Not authorized")
    
    if current_user.get("role") not in ["admin", "franchise"]:
        raise HTTPException(status_code=403, detail="Not authorized")
    
    await db.packages.delete_one({"id": package_id})
    
    return {"success": True, "message": "Package deleted successfully"}

@package_router.get("/statistics/overview")
async def get_package_statistics(
    current_user: dict = Depends(get_current_user)
):
    """Get package statistics and analytics"""
    try:
        # Get all packages
        packages = await db.packages.find({}).to_list(1000)
        
        # Get enrollments with package info
        enrollments = await db.enrollments.find({}).to_list(10000)
        
        # Calculate statistics
        total_packages = len(packages)
        active_packages = len([p for p in packages if p.get("is_active")])
        
        # Package popularity (count enrollments per package)
        package_enrollments = {}
        for enrollment in enrollments:
            pkg_id = enrollment.get("package_id")
            if pkg_id:
                package_enrollments[pkg_id] = package_enrollments.get(pkg_id, 0) + 1
        
        # Revenue by package
        payments = await db.payments.find({"status": "success"}).to_list(10000)
        package_revenue = {}
        for payment in payments:
            enrollment = await db.enrollments.find_one({"id": payment.get("enrollment_id")})
            if enrollment:
                pkg_id = enrollment.get("package_id")
                if pkg_id:
                    package_revenue[pkg_id] = package_revenue.get(pkg_id, 0) + payment.get("total_amount", 0)
        
        # Most popular packages
        popular_packages = sorted(
            [
                {
                    "package_id": pkg_id,
                    "package_name": next((p.get("name") for p in packages if p.get("id") == pkg_id), "Unknown"),
                    "enrollments": count
                }
                for pkg_id, count in package_enrollments.items()
            ],
            key=lambda x: x["enrollments"],
            reverse=True
        )[:5]
        
        # Revenue by package (top 5)
        top_revenue_packages = sorted(
            [
                {
                    "package_id": pkg_id,
                    "package_name": next((p.get("name") for p in packages if p.get("id") == pkg_id), "Unknown"),
                    "revenue": revenue
                }
                for pkg_id, revenue in package_revenue.items()
            ],
            key=lambda x: x["revenue"],
            reverse=True
        )[:5]
        
        # Brand distribution
        brand_distribution = {}
        for pkg in packages:
            brand = pkg.get("brand", "unknown")
            brand_distribution[brand] = brand_distribution.get(brand, 0) + 1
        
        return {
            "success": True,
            "statistics": {
                "total_packages": total_packages,
                "active_packages": active_packages,
                "inactive_packages": total_packages - active_packages,
                "total_enrollments": len(enrollments),
                "popular_packages": popular_packages,
                "top_revenue_packages": top_revenue_packages,
                "brand_distribution": brand_distribution
            }
        }
    
    except Exception as e:
        print(f"Error fetching package statistics: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

