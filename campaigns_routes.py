"""
Campaigns & Marketing Routes
Campaign creation, scheduling, tracking, and ROI analytics
"""
from fastapi import APIRouter, Depends, HTTPException, Query
from typing import Optional, List, Dict, Any
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

campaigns_router = APIRouter(prefix="/api/campaigns", tags=["Campaigns & Marketing"])

# ==================== MODELS ====================

class CampaignCreate(BaseModel):
    name: str
    description: Optional[str] = None
    message_template: str
    target_audience: str  # "all", "parents", "leads", "inactive_members"
    channels: List[str] = ["push"]  # "push", "whatsapp", "email", "sms"
    schedule_type: str = "immediate"  # "immediate", "scheduled"
    schedule_time: Optional[datetime] = None
    filters: Optional[Dict[str, Any]] = None

class CampaignUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    message_template: Optional[str] = None
    schedule_type: Optional[str] = None
    schedule_time: Optional[datetime] = None
    status: Optional[str] = None

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

async def get_target_audience(target: str, filters: Dict = None):
    """Get list of recipients based on target audience"""
    recipients = []
    
    if target == "all_parents":
        users = await db.users.find({"role": "parent"}).to_list(10000)
        recipients = [{"phone": u.get("phone"), "name": u.get("name"), "email": u.get("email")} for u in users]
    
    elif target == "all_leads":
        leads = await db.leads.find({"status": {"$ne": "enrolled"}}).to_list(10000)
        recipients = [{"phone": l.get("phone"), "name": l.get("name"), "email": l.get("email")} for l in leads]
    
    elif target == "inactive_members":
        # Members with no attendance in last 14 days
        from datetime import timedelta
        two_weeks_ago = datetime.utcnow() - timedelta(days=14)
        
        enrollments = await db.enrollments.find({"status": "active"}).to_list(10000)
        for enrollment in enrollments:
            recent_attendance = await db.attendance.find_one({
                "child_id": enrollment.get("child_id"),
                "created_at": {"$gte": two_weeks_ago}
            })
            
            if not recent_attendance:
                child = await db.children.find_one({"id": enrollment.get("child_id")})
                if child:
                    parent = await db.users.find_one({"id": child.get("parent_id")})
                    if parent:
                        recipients.append({
                            "phone": parent.get("phone"),
                            "name": parent.get("name"),
                            "email": parent.get("email")
                        })
    
    elif target == "high_value":
        # Members who spent more than ₹20,000
        payments = await db.payments.find({"status": "success"}).to_list(10000)
        
        # Group by enrollment/parent
        parent_spending = {}
        for payment in payments:
            enrollment = await db.enrollments.find_one({"id": payment.get("enrollment_id")})
            if enrollment:
                parent_id = enrollment.get("parent_id")
                parent_spending[parent_id] = parent_spending.get(parent_id, 0) + payment.get("total_amount", 0)
        
        for parent_id, total in parent_spending.items():
            if total >= 20000:
                parent = await db.users.find_one({"id": parent_id})
                if parent:
                    recipients.append({
                        "phone": parent.get("phone"),
                        "name": parent.get("name"),
                        "email": parent.get("email")
                    })
    
    # Remove duplicates
    unique_recipients = []
    seen_phones = set()
    for r in recipients:
        if r["phone"] not in seen_phones:
            unique_recipients.append(r)
            seen_phones.add(r["phone"])
    
    return unique_recipients

# ==================== CAMPAIGN CRUD ====================

@campaigns_router.get("")
async def list_campaigns(
    status: Optional[str] = None,
    limit: int = Query(50, le=200),
    current_user: dict = Depends(get_current_user)
):
    """List all campaigns"""
    try:
        query = {}
        if status:
            query["status"] = status
        
        campaigns = await db.campaigns.find(query).sort("created_at", -1).to_list(limit)
        
        return {
            "success": True,
            "campaigns": [serialize_doc(c) for c in campaigns],
            "total": len(campaigns)
        }
    
    except Exception as e:
        print(f"Error listing campaigns: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@campaigns_router.post("")
async def create_campaign(
    campaign_data: CampaignCreate,
    current_user: dict = Depends(get_current_user)
):
    """Create a new campaign"""
    try:
        # Check authorization
        if current_user.get("role") not in ["admin", "franchise", "manager"]:
            raise HTTPException(status_code=403, detail="Not authorized")
        
        # Get target audience
        recipients = await get_target_audience(
            campaign_data.target_audience,
            campaign_data.filters
        )
        
        # Create campaign document
        campaign_doc = {
            "id": str(__import__('uuid').uuid4()),
            "name": campaign_data.name,
            "description": campaign_data.description,
            "message_template": campaign_data.message_template,
            "target_audience": campaign_data.target_audience,
            "channels": campaign_data.channels,
            "schedule_type": campaign_data.schedule_type,
            "schedule_time": campaign_data.schedule_time,
            "status": "draft" if campaign_data.schedule_type == "scheduled" else "pending",
            "recipients_count": len(recipients),
            "sent_count": 0,
            "delivered_count": 0,
            "opened_count": 0,
            "clicked_count": 0,
            "created_by": current_user["sub"],
            "created_at": datetime.utcnow(),
            "updated_at": datetime.utcnow()
        }
        
        await db.campaigns.insert_one(campaign_doc)
        
        return {
            "success": True,
            "campaign_id": campaign_doc["id"],
            "message": "Campaign created successfully",
            "recipients_count": len(recipients)
        }
    
    except Exception as e:
        print(f"Error creating campaign: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@campaigns_router.get("/{campaign_id}")
async def get_campaign(
    campaign_id: str,
    current_user: dict = Depends(get_current_user)
):
    """Get campaign details"""
    try:
        campaign = await db.campaigns.find_one({"id": campaign_id})
        if not campaign:
            raise HTTPException(status_code=404, detail="Campaign not found")
        
        return {
            "success": True,
            "campaign": serialize_doc(campaign)
        }
    
    except HTTPException as he:
        raise he
    except Exception as e:
        print(f"Error getting campaign: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@campaigns_router.patch("/{campaign_id}")
async def update_campaign(
    campaign_id: str,
    update_data: CampaignUpdate,
    current_user: dict = Depends(get_current_user)
):
    """Update campaign"""
    try:
        campaign = await db.campaigns.find_one({"id": campaign_id})
        if not campaign:
            raise HTTPException(status_code=404, detail="Campaign not found")
        
        # Build update dict
        update_dict = {"updated_at": datetime.utcnow()}
        
        if update_data.name:
            update_dict["name"] = update_data.name
        if update_data.description:
            update_dict["description"] = update_data.description
        if update_data.message_template:
            update_dict["message_template"] = update_data.message_template
        if update_data.schedule_type:
            update_dict["schedule_type"] = update_data.schedule_type
        if update_data.schedule_time:
            update_dict["schedule_time"] = update_data.schedule_time
        if update_data.status:
            update_dict["status"] = update_data.status
        
        await db.campaigns.update_one(
            {"id": campaign_id},
            {"$set": update_dict}
        )
        
        return {
            "success": True,
            "message": "Campaign updated successfully"
        }
    
    except HTTPException as he:
        raise he
    except Exception as e:
        print(f"Error updating campaign: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@campaigns_router.delete("/{campaign_id}")
async def delete_campaign(
    campaign_id: str,
    current_user: dict = Depends(get_current_user)
):
    """Delete campaign"""
    try:
        campaign = await db.campaigns.find_one({"id": campaign_id})
        if not campaign:
            raise HTTPException(status_code=404, detail="Campaign not found")
        
        # Only delete if not sent
        if campaign.get("status") in ["sent", "sending"]:
            raise HTTPException(status_code=400, detail="Cannot delete sent campaigns")
        
        await db.campaigns.delete_one({"id": campaign_id})
        
        return {
            "success": True,
            "message": "Campaign deleted successfully"
        }
    
    except HTTPException as he:
        raise he
    except Exception as e:
        print(f"Error deleting campaign: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

# ==================== CAMPAIGN EXECUTION ====================

@campaigns_router.post("/{campaign_id}/send")
async def send_campaign(
    campaign_id: str,
    current_user: dict = Depends(get_current_user)
):
    """Send campaign to recipients"""
    try:
        campaign = await db.campaigns.find_one({"id": campaign_id})
        if not campaign:
            raise HTTPException(status_code=404, detail="Campaign not found")
        
        if campaign.get("status") == "sent":
            raise HTTPException(status_code=400, detail="Campaign already sent")
        
        # Get recipients
        recipients = await get_target_audience(
            campaign.get("target_audience"),
            campaign.get("filters")
        )
        
        # Update campaign status
        await db.campaigns.update_one(
            {"id": campaign_id},
            {"$set": {
                "status": "sent",
                "sent_count": len(recipients),
                "sent_at": datetime.utcnow()
            }}
        )
        
        # In production, integrate with actual notification services
        # For now, we'll just mark as sent
        print(f"Campaign '{campaign.get('name')}' sent to {len(recipients)} recipients")
        
        return {
            "success": True,
            "message": f"Campaign sent to {len(recipients)} recipients",
            "recipients_count": len(recipients)
        }
    
    except HTTPException as he:
        raise he
    except Exception as e:
        print(f"Error sending campaign: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

# ==================== CAMPAIGN ANALYTICS ====================

@campaigns_router.get("/{campaign_id}/analytics")
async def get_campaign_analytics(
    campaign_id: str,
    current_user: dict = Depends(get_current_user)
):
    """Get campaign performance analytics"""
    try:
        campaign = await db.campaigns.find_one({"id": campaign_id})
        if not campaign:
            raise HTTPException(status_code=404, detail="Campaign not found")
        
        # Calculate metrics
        sent_count = campaign.get("sent_count", 0)
        delivered_count = campaign.get("delivered_count", sent_count)  # Assume all delivered
        opened_count = campaign.get("opened_count", int(delivered_count * 0.35))  # Mock: 35% open rate
        clicked_count = campaign.get("clicked_count", int(opened_count * 0.15))  # Mock: 15% click rate
        
        # Calculate rates
        delivery_rate = (delivered_count / sent_count * 100) if sent_count > 0 else 0
        open_rate = (opened_count / delivered_count * 100) if delivered_count > 0 else 0
        click_rate = (clicked_count / opened_count * 100) if opened_count > 0 else 0
        
        # Calculate ROI (mock calculation)
        # Assume average conversion value of ₹10,000 and 5% conversion rate
        conversions = int(clicked_count * 0.05)
        revenue = conversions * 10000
        cost = sent_count * 0.5  # ₹0.50 per message
        roi = ((revenue - cost) / cost * 100) if cost > 0 else 0
        
        return {
            "success": True,
            "analytics": {
                "campaign_id": campaign_id,
                "campaign_name": campaign.get("name"),
                "status": campaign.get("status"),
                "metrics": {
                    "sent": sent_count,
                    "delivered": delivered_count,
                    "opened": opened_count,
                    "clicked": clicked_count,
                    "conversions": conversions
                },
                "rates": {
                    "delivery_rate": round(delivery_rate, 2),
                    "open_rate": round(open_rate, 2),
                    "click_rate": round(click_rate, 2),
                    "conversion_rate": round((conversions / sent_count * 100) if sent_count > 0 else 0, 2)
                },
                "roi": {
                    "revenue": revenue,
                    "cost": cost,
                    "roi_percentage": round(roi, 2)
                }
            }
        }
    
    except HTTPException as he:
        raise he
    except Exception as e:
        print(f"Error getting campaign analytics: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

# ==================== CAMPAIGN STATISTICS ====================

@campaigns_router.get("/statistics/overview")
async def get_campaigns_overview(
    current_user: dict = Depends(get_current_user)
):
    """Get overall campaigns performance statistics"""
    try:
        # Get all campaigns
        campaigns = await db.campaigns.find({}).to_list(1000)
        
        total_campaigns = len(campaigns)
        active_campaigns = sum(1 for c in campaigns if c.get("status") in ["pending", "sending", "scheduled"])
        sent_campaigns = sum(1 for c in campaigns if c.get("status") == "sent")
        
        total_sent = sum(c.get("sent_count", 0) for c in campaigns)
        total_delivered = sum(c.get("delivered_count", c.get("sent_count", 0)) for c in campaigns)
        total_opened = sum(c.get("opened_count", 0) for c in campaigns)
        
        avg_open_rate = (total_opened / total_delivered * 100) if total_delivered > 0 else 0
        
        # Recent campaigns
        recent_campaigns = sorted(
            campaigns,
            key=lambda x: x.get("created_at", datetime.min),
            reverse=True
        )[:5]
        
        return {
            "success": True,
            "statistics": {
                "total_campaigns": total_campaigns,
                "active_campaigns": active_campaigns,
                "sent_campaigns": sent_campaigns,
                "total_messages_sent": total_sent,
                "average_open_rate": round(avg_open_rate, 2),
                "recent_campaigns": [serialize_doc(c) for c in recent_campaigns]
            }
        }
    
    except Exception as e:
        print(f"Error getting campaigns overview: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))
