"""
AI Insights & Analytics Routes
Predictive analytics, churn prediction, revenue forecasting
"""
from fastapi import APIRouter, Depends, HTTPException, Query
from typing import Optional, List, Dict, Any
from datetime import datetime, timedelta
from motor.motor_asyncio import AsyncIOMotorClient
from pathlib import Path
import os
from dotenv import load_dotenv
import random

from auth import get_current_user

# Load environment variables
ROOT_DIR = Path(__file__).parent
load_dotenv(ROOT_DIR / '.env')

# MongoDB connection
mongo_url = os.environ['MONGO_URL']
client = AsyncIOMotorClient(mongo_url)
db = client[os.environ['DB_NAME']]

ai_insights_router = APIRouter(prefix="/api/ai-insights", tags=["AI Insights"])

# ==================== HELPER FUNCTIONS ====================

def serialize_doc(doc: dict) -> dict:
    """Convert MongoDB document to JSON-serializable dict"""
    if not doc:
        return None
    if "_id" in doc:
        del doc["_id"]
    return doc

def calculate_churn_risk_score(member_data: dict) -> float:
    """Calculate churn risk score (0-100) based on various factors"""
    score = 0.0
    
    # Attendance rate (40% weight)
    attendance_rate = member_data.get("attendance_rate", 0)
    if attendance_rate < 30:
        score += 40
    elif attendance_rate < 50:
        score += 25
    elif attendance_rate < 70:
        score += 10
    
    # Days since last visit (30% weight)
    days_since_last = member_data.get("days_since_last_visit", 0)
    if days_since_last > 14:
        score += 30
    elif days_since_last > 7:
        score += 15
    
    # Enrollment end approaching (20% weight)
    days_until_end = member_data.get("days_until_end", 365)
    if days_until_end < 7:
        score += 20
    elif days_until_end < 30:
        score += 10
    
    # Payment history (10% weight)
    failed_payments = member_data.get("failed_payments", 0)
    score += min(failed_payments * 5, 10)
    
    return min(score, 100)

def predict_ltv(member_data: dict) -> float:
    """Predict Customer Lifetime Value"""
    # Simple LTV calculation: avg_payment * predicted_months
    avg_payment = member_data.get("avg_payment", 12000)
    attendance_rate = member_data.get("attendance_rate", 70)
    months_enrolled = member_data.get("months_enrolled", 3)
    
    # Higher attendance = longer retention
    retention_factor = attendance_rate / 100
    predicted_months = months_enrolled * (1 + retention_factor)
    
    ltv = avg_payment * predicted_months
    return round(ltv, 2)

# ==================== CHURN PREDICTION ====================

@ai_insights_router.get("/churn-prediction")
async def get_churn_predictions(
    risk_level: Optional[str] = Query(None, regex="^(high|medium|low)$"),
    center_id: Optional[str] = None,
    limit: int = Query(50, le=200),
    current_user: dict = Depends(get_current_user)
):
    """Get members at risk of churning with risk scores"""
    try:
        # Get all active enrollments
        query = {"status": "active"}
        if center_id:
            query["center_id"] = center_id
        
        enrollments = await db.enrollments.find(query).to_list(1000)
        
        churn_predictions = []
        
        for enrollment in enrollments:
            # Get child info
            child = await db.children.find_one({"id": enrollment.get("child_id")})
            if not child:
                continue
            
            # Get parent info
            parent = await db.users.find_one({"id": child.get("parent_id")})
            if not parent:
                continue
            
            # Calculate attendance rate
            class_id = enrollment.get("class_id")
            attendance_records = await db.attendance.find({
                "child_id": child["id"],
                "class_id": class_id
            }).to_list(1000)
            
            present_count = sum(1 for a in attendance_records if a.get("status") == "present")
            attendance_rate = (present_count / len(attendance_records) * 100) if attendance_records else 0
            
            # Days since last visit
            last_attendance = max(
                [a.get("created_at", datetime.min) for a in attendance_records],
                default=datetime.min
            )
            days_since_last = (datetime.utcnow() - last_attendance).days if last_attendance != datetime.min else 999
            
            # Days until enrollment ends
            end_date = enrollment.get("end_date")
            if isinstance(end_date, str):
                end_date = datetime.fromisoformat(end_date)
            days_until_end = (end_date - datetime.utcnow()).days if end_date else 365
            
            # Get payment history
            payments = await db.payments.find({"enrollment_id": enrollment["id"]}).to_list(100)
            failed_payments = sum(1 for p in payments if p.get("status") == "failed")
            avg_payment = sum(p.get("total_amount", 0) for p in payments) / len(payments) if payments else 12000
            
            # Calculate churn risk
            member_data = {
                "attendance_rate": attendance_rate,
                "days_since_last_visit": days_since_last,
                "days_until_end": days_until_end,
                "failed_payments": failed_payments,
                "avg_payment": avg_payment,
                "months_enrolled": max((datetime.utcnow() - enrollment.get("created_at", datetime.utcnow())).days // 30, 1)
            }
            
            risk_score = calculate_churn_risk_score(member_data)
            
            # Determine risk level
            if risk_score >= 70:
                risk = "high"
            elif risk_score >= 40:
                risk = "medium"
            else:
                risk = "low"
            
            # Filter by risk level if specified
            if risk_level and risk != risk_level:
                continue
            
            # Calculate LTV
            ltv = predict_ltv(member_data)
            
            churn_predictions.append({
                "enrollment_id": enrollment["id"],
                "child_name": child.get("name"),
                "parent_name": parent.get("name"),
                "parent_phone": parent.get("phone"),
                "risk_score": round(risk_score, 2),
                "risk_level": risk,
                "attendance_rate": round(attendance_rate, 2),
                "days_since_last_visit": days_since_last,
                "days_until_end": days_until_end,
                "predicted_ltv": ltv,
                "recommendations": get_retention_recommendations(risk, member_data)
            })
        
        # Sort by risk score (highest first)
        churn_predictions.sort(key=lambda x: x["risk_score"], reverse=True)
        
        return {
            "success": True,
            "predictions": churn_predictions[:limit],
            "total": len(churn_predictions),
            "summary": {
                "high_risk": sum(1 for p in churn_predictions if p["risk_level"] == "high"),
                "medium_risk": sum(1 for p in churn_predictions if p["risk_level"] == "medium"),
                "low_risk": sum(1 for p in churn_predictions if p["risk_level"] == "low")
            }
        }
    
    except Exception as e:
        print(f"Error in churn prediction: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

def get_retention_recommendations(risk_level: str, member_data: dict) -> List[str]:
    """Get actionable recommendations to reduce churn"""
    recommendations = []
    
    if member_data["attendance_rate"] < 50:
        recommendations.append("Schedule a check-in call to understand barriers to attendance")
        recommendations.append("Offer makeup classes to improve engagement")
    
    if member_data["days_since_last_visit"] > 14:
        recommendations.append("Send re-engagement message with special offer")
        recommendations.append("Call parent to address concerns")
    
    if member_data["days_until_end"] < 30:
        recommendations.append("Offer early renewal discount (10-15% off)")
        recommendations.append("Share child's progress report to show value")
    
    if member_data["failed_payments"] > 0:
        recommendations.append("Update payment method and offer payment plan")
    
    if risk_level == "high":
        recommendations.append("URGENT: Personal call from center manager")
        recommendations.append("Offer free trial of new program or class")
    
    return recommendations

# ==================== REVENUE FORECASTING ====================

@ai_insights_router.get("/revenue-forecast")
async def get_revenue_forecast(
    period: str = Query("quarter", regex="^(month|quarter|year)$"),
    center_id: Optional[str] = None,
    current_user: dict = Depends(get_current_user)
):
    """Forecast future revenue based on historical data"""
    try:
        # Get historical revenue data
        payments = await db.payments.find({"status": "success"}).to_list(10000)
        
        # Filter by center if specified
        if center_id:
            enrollments = await db.enrollments.find({"center_id": center_id}).to_list(10000)
            enrollment_ids = [e["id"] for e in enrollments]
            payments = [p for p in payments if p.get("enrollment_id") in enrollment_ids]
        
        # Calculate historical averages
        now = datetime.utcnow()
        last_30_days = [p for p in payments if (now - p.get("created_at", now)).days <= 30]
        last_90_days = [p for p in payments if (now - p.get("created_at", now)).days <= 90]
        
        monthly_avg = sum(p.get("total_amount", 0) for p in last_30_days)
        quarterly_avg = sum(p.get("total_amount", 0) for p in last_90_days)
        
        # Apply growth rate (assume 10% growth)
        growth_rate = 1.10
        
        # Forecast based on period
        if period == "month":
            forecast = monthly_avg * growth_rate
            confidence = 85
        elif period == "quarter":
            forecast = quarterly_avg * growth_rate
            confidence = 75
        else:  # year
            forecast = (quarterly_avg * 4) * growth_rate
            confidence = 60
        
        # Calculate trends
        trends = {
            "current_month": monthly_avg,
            "projected_growth": f"+{(growth_rate - 1) * 100:.1f}%",
            "confidence_level": f"{confidence}%"
        }
        
        return {
            "success": True,
            "forecast": {
                "period": period,
                "predicted_revenue": round(forecast, 2),
                "confidence_score": confidence,
                "historical_average": round(quarterly_avg if period != "month" else monthly_avg, 2),
                "growth_rate": growth_rate,
                "trends": trends
            }
        }
    
    except Exception as e:
        print(f"Error in revenue forecast: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

# ==================== ENROLLMENT TRENDS ====================

@ai_insights_router.get("/enrollment-trends")
async def get_enrollment_trends(
    period: str = Query("month", regex="^(week|month|quarter|year)$"),
    center_id: Optional[str] = None,
    current_user: dict = Depends(get_current_user)
):
    """Analyze enrollment trends and patterns"""
    try:
        # Get all enrollments
        query = {}
        if center_id:
            query["center_id"] = center_id
        
        enrollments = await db.enrollments.find(query).to_list(10000)
        
        # Group by time period
        now = datetime.utcnow()
        periods = []
        
        if period == "week":
            num_periods = 12  # Last 12 weeks
            days_per_period = 7
        elif period == "month":
            num_periods = 12  # Last 12 months
            days_per_period = 30
        elif period == "quarter":
            num_periods = 8  # Last 8 quarters
            days_per_period = 90
        else:  # year
            num_periods = 5  # Last 5 years
            days_per_period = 365
        
        for i in range(num_periods):
            period_start = now - timedelta(days=(i + 1) * days_per_period)
            period_end = now - timedelta(days=i * days_per_period)
            
            period_enrollments = [
                e for e in enrollments
                if period_start <= e.get("created_at", datetime.min) < period_end
            ]
            
            periods.append({
                "period": period_start.strftime("%Y-%m-%d"),
                "enrollments": len(period_enrollments),
                "revenue": sum(
                    p.get("total_amount", 0)
                    for e in period_enrollments
                    for p in await db.payments.find({"enrollment_id": e["id"], "status": "success"}).to_list(10)
                )
            })
        
        periods.reverse()  # Oldest to newest
        
        # Calculate trend
        if len(periods) >= 2:
            recent_avg = sum(p["enrollments"] for p in periods[-3:]) / 3
            older_avg = sum(p["enrollments"] for p in periods[:3]) / 3
            trend = "increasing" if recent_avg > older_avg else "decreasing"
            change_pct = ((recent_avg - older_avg) / older_avg * 100) if older_avg > 0 else 0
        else:
            trend = "stable"
            change_pct = 0
        
        return {
            "success": True,
            "trends": {
                "period": period,
                "data": periods,
                "trend_direction": trend,
                "change_percentage": round(change_pct, 2),
                "total_enrollments": len(enrollments)
            }
        }
    
    except Exception as e:
        print(f"Error in enrollment trends: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

# ==================== PROGRAM PERFORMANCE ====================

@ai_insights_router.get("/program-performance")
async def get_program_performance(
    current_user: dict = Depends(get_current_user)
):
    """Analyze performance metrics for each program"""
    try:
        # Get all programs
        programs = await db.programs.find({}).to_list(100)
        
        performance_data = []
        
        for program in programs:
            program_id = program.get("id")
            
            # Get enrollments for this program
            enrollments = await db.enrollments.find({"program_id": program_id}).to_list(1000)
            
            # Calculate metrics
            total_enrollments = len(enrollments)
            active_enrollments = sum(1 for e in enrollments if e.get("status") == "active")
            
            # Calculate revenue
            enrollment_ids = [e["id"] for e in enrollments]
            payments = await db.payments.find({
                "enrollment_id": {"$in": enrollment_ids},
                "status": "success"
            }).to_list(1000)
            total_revenue = sum(p.get("total_amount", 0) for p in payments)
            
            # Calculate average attendance
            attendance_records = []
            for enrollment in enrollments:
                records = await db.attendance.find({"child_id": enrollment.get("child_id")}).to_list(1000)
                attendance_records.extend(records)
            
            present_count = sum(1 for a in attendance_records if a.get("status") == "present")
            attendance_rate = (present_count / len(attendance_records) * 100) if attendance_records else 0
            
            performance_data.append({
                "program_id": program_id,
                "program_name": program.get("name"),
                "brand": program.get("brand"),
                "level": program.get("level"),
                "total_enrollments": total_enrollments,
                "active_enrollments": active_enrollments,
                "total_revenue": round(total_revenue, 2),
                "avg_revenue_per_enrollment": round(total_revenue / total_enrollments, 2) if total_enrollments > 0 else 0,
                "attendance_rate": round(attendance_rate, 2),
                "performance_score": round((attendance_rate + (active_enrollments / max(total_enrollments, 1) * 100)) / 2, 2)
            })
        
        # Sort by performance score
        performance_data.sort(key=lambda x: x["performance_score"], reverse=True)
        
        return {
            "success": True,
            "programs": performance_data,
            "summary": {
                "total_programs": len(programs),
                "best_performing": performance_data[0] if performance_data else None,
                "avg_performance": round(sum(p["performance_score"] for p in performance_data) / len(performance_data), 2) if performance_data else 0
            }
        }
    
    except Exception as e:
        print(f"Error in program performance: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

# ==================== DASHBOARD SUMMARY ====================

@ai_insights_router.get("/dashboard-summary")
async def get_ai_dashboard_summary(
    current_user: dict = Depends(get_current_user)
):
    """Get comprehensive AI insights summary for dashboard"""
    try:
        # Get churn predictions summary
        churn_data = await get_churn_predictions(risk_level=None, current_user=current_user)
        
        # Get revenue forecast
        revenue_data = await get_revenue_forecast(period="quarter", current_user=current_user)
        
        # Get enrollment trends
        trends_data = await get_enrollment_trends(period="month", current_user=current_user)
        
        # Get program performance
        program_data = await get_program_performance(current_user=current_user)
        
        return {
            "success": True,
            "summary": {
                "churn_risk": {
                    "high_risk_count": churn_data["summary"]["high_risk"],
                    "medium_risk_count": churn_data["summary"]["medium_risk"],
                    "total_at_risk": churn_data["summary"]["high_risk"] + churn_data["summary"]["medium_risk"]
                },
                "revenue_forecast": revenue_data["forecast"],
                "enrollment_trends": {
                    "direction": trends_data["trends"]["trend_direction"],
                    "change_pct": trends_data["trends"]["change_percentage"]
                },
                "program_performance": {
                    "best_program": program_data["summary"]["best_performing"],
                    "avg_performance": program_data["summary"]["avg_performance"]
                }
            }
        }
    
    except Exception as e:
        print(f"Error in AI dashboard summary: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))
