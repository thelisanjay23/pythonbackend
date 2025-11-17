"""
Data Export Routes
Export data to PDF and Excel formats
"""
from fastapi import APIRouter, Depends, HTTPException, Query, Response
from typing import Optional, List
from datetime import datetime
from motor.motor_asyncio import AsyncIOMotorClient
from pathlib import Path
import os
from dotenv import load_dotenv
import io
import csv

from auth import get_current_user
from pdf_generator import generate_pdf_invoice
from reportlab.lib import colors
from reportlab.lib.pagesizes import letter, A4
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch

# Load environment variables
ROOT_DIR = Path(__file__).parent
load_dotenv(ROOT_DIR / '.env')

# MongoDB connection
mongo_url = os.environ['MONGO_URL']
client = AsyncIOMotorClient(mongo_url)
db = client[os.environ['DB_NAME']]

export_router = APIRouter(prefix="/api/export", tags=["Data Export"])

# ==================== HELPER FUNCTIONS ====================

def serialize_doc(doc: dict) -> dict:
    """Convert MongoDB document to JSON-serializable dict"""
    if not doc:
        return None
    if "_id" in doc:
        del doc["_id"]
    # Convert datetime objects to ISO strings
    for key, value in doc.items():
        if isinstance(value, datetime):
            doc[key] = value.isoformat()
    return doc

# ==================== MEMBERS EXPORT ====================

@export_router.get("/members/csv")
async def export_members_csv(
    center_id: Optional[str] = None,
    status: Optional[str] = None,
    current_user: dict = Depends(get_current_user)
):
    """Export members list to CSV"""
    try:
        # Check authorization
        if current_user.get("role") not in ["admin", "franchise", "manager"]:
            raise HTTPException(status_code=403, detail="Not authorized")
        
        # Get all parents
        parents = await db.users.find({"role": "parent"}).to_list(1000)
        
        # Create CSV in memory
        output = io.StringIO()
        writer = csv.writer(output)
        
        # Write header
        writer.writerow([
            "Parent Name", "Phone", "Email", "Children Count", 
            "Active Enrollments", "Total Spent", "Join Date"
        ])
        
        # Write data rows
        for parent in parents:
            # Get children
            children = await db.children.find({"parent_id": parent["id"]}).to_list(100)
            
            # Get enrollments
            child_ids = [c["id"] for c in children]
            enrollments = await db.enrollments.find({"child_id": {"$in": child_ids}}).to_list(100)
            
            if center_id:
                enrollments = [e for e in enrollments if e.get("center_id") == center_id]
            
            if status:
                enrollments = [e for e in enrollments if e.get("status") == status]
            
            # Get payments
            enrollment_ids = [e["id"] for e in enrollments]
            payments = await db.payments.find({
                "enrollment_id": {"$in": enrollment_ids},
                "status": "success"
            }).to_list(1000)
            total_spent = sum(p.get("total_amount", 0) for p in payments)
            
            active_enrollments = sum(1 for e in enrollments if e.get("status") == "active")
            
            writer.writerow([
                parent.get("name", ""),
                parent.get("phone", ""),
                parent.get("email", ""),
                len(children),
                active_enrollments,
                f"₹{total_spent:,.2f}",
                parent.get("created_at", datetime.utcnow()).strftime("%Y-%m-%d") if isinstance(parent.get("created_at"), datetime) else ""
            ])
        
        # Get CSV content
        csv_content = output.getvalue()
        output.close()
        
        # Return as downloadable file
        return Response(
            content=csv_content,
            media_type="text/csv",
            headers={
                "Content-Disposition": f"attachment; filename=members_export_{datetime.utcnow().strftime('%Y%m%d')}.csv"
            }
        )
    
    except Exception as e:
        print(f"Error exporting members CSV: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@export_router.get("/members/pdf")
async def export_members_pdf(
    center_id: Optional[str] = None,
    current_user: dict = Depends(get_current_user)
):
    """Export members list to PDF"""
    try:
        # Check authorization
        if current_user.get("role") not in ["admin", "franchise", "manager"]:
            raise HTTPException(status_code=403, detail="Not authorized")
        
        # Get all parents
        parents = await db.users.find({"role": "parent"}).to_list(1000)
        
        # Create PDF in memory
        buffer = io.BytesIO()
        doc = SimpleDocTemplate(buffer, pagesize=A4)
        elements = []
        
        # Styles
        styles = getSampleStyleSheet()
        title_style = ParagraphStyle(
            'CustomTitle',
            parent=styles['Heading1'],
            fontSize=24,
            textColor=colors.HexColor('#FF1493'),
            spaceAfter=30,
            alignment=1  # Center
        )
        
        # Title
        elements.append(Paragraph("Tumble Gym - Members Report", title_style))
        elements.append(Paragraph(f"Generated on: {datetime.utcnow().strftime('%Y-%m-%d %H:%M')}", styles['Normal']))
        elements.append(Spacer(1, 0.5 * inch))
        
        # Table data
        data = [["Parent Name", "Phone", "Children", "Active Enrollments", "Total Spent"]]
        
        for parent in parents:
            children = await db.children.find({"parent_id": parent["id"]}).to_list(100)
            child_ids = [c["id"] for c in children]
            enrollments = await db.enrollments.find({"child_id": {"$in": child_ids}}).to_list(100)
            
            if center_id:
                enrollments = [e for e in enrollments if e.get("center_id") == center_id]
            
            enrollment_ids = [e["id"] for e in enrollments]
            payments = await db.payments.find({
                "enrollment_id": {"$in": enrollment_ids},
                "status": "success"
            }).to_list(1000)
            total_spent = sum(p.get("total_amount", 0) for p in payments)
            
            active_enrollments = sum(1 for e in enrollments if e.get("status") == "active")
            
            data.append([
                parent.get("name", "")[:25],
                parent.get("phone", ""),
                str(len(children)),
                str(active_enrollments),
                f"₹{total_spent:,.0f}"
            ])
        
        # Create table
        table = Table(data)
        table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#FF1493')),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
            ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('FONTSIZE', (0, 0), (-1, 0), 12),
            ('BOTTOMPADDING', (0, 0), (-1, 0), 12),
            ('BACKGROUND', (0, 1), (-1, -1), colors.beige),
            ('GRID', (0, 0), (-1, -1), 1, colors.black)
        ]))
        
        elements.append(table)
        
        # Build PDF
        doc.build(elements)
        
        # Get PDF content
        pdf_content = buffer.getvalue()
        buffer.close()
        
        return Response(
            content=pdf_content,
            media_type="application/pdf",
            headers={
                "Content-Disposition": f"attachment; filename=members_report_{datetime.utcnow().strftime('%Y%m%d')}.pdf"
            }
        )
    
    except Exception as e:
        print(f"Error exporting members PDF: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

# ==================== PAYMENTS EXPORT ====================

@export_router.get("/payments/csv")
async def export_payments_csv(
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    center_id: Optional[str] = None,
    current_user: dict = Depends(get_current_user)
):
    """Export payments to CSV"""
    try:
        # Check authorization
        if current_user.get("role") not in ["admin", "franchise", "manager"]:
            raise HTTPException(status_code=403, detail="Not authorized")
        
        # Build query
        query = {"status": "success"}
        
        if start_date and end_date:
            query["created_at"] = {
                "$gte": datetime.fromisoformat(start_date),
                "$lte": datetime.fromisoformat(end_date)
            }
        
        payments = await db.payments.find(query).to_list(10000)
        
        # Filter by center if specified
        if center_id:
            enrollments = await db.enrollments.find({"center_id": center_id}).to_list(10000)
            enrollment_ids = [e["id"] for e in enrollments]
            payments = [p for p in payments if p.get("enrollment_id") in enrollment_ids]
        
        # Create CSV
        output = io.StringIO()
        writer = csv.writer(output)
        
        # Header
        writer.writerow([
            "Date", "Invoice Number", "Parent Name", "Child Name", 
            "Amount", "Tax", "Total", "Payment ID", "Status"
        ])
        
        # Data rows
        for payment in payments:
            # Get enrollment and child
            enrollment = await db.enrollments.find_one({"id": payment.get("enrollment_id")})
            if not enrollment:
                continue
            
            child = await db.children.find_one({"id": enrollment.get("child_id")})
            parent = await db.users.find_one({"id": enrollment.get("parent_id")})
            
            writer.writerow([
                payment.get("created_at", datetime.utcnow()).strftime("%Y-%m-%d") if isinstance(payment.get("created_at"), datetime) else "",
                payment.get("invoice_number", ""),
                parent.get("name", "") if parent else "",
                child.get("name", "") if child else "",
                f"₹{payment.get('amount', 0):,.2f}",
                f"₹{payment.get('tax_amount', 0):,.2f}",
                f"₹{payment.get('total_amount', 0):,.2f}",
                payment.get("razorpay_payment_id", ""),
                payment.get("status", "")
            ])
        
        csv_content = output.getvalue()
        output.close()
        
        return Response(
            content=csv_content,
            media_type="text/csv",
            headers={
                "Content-Disposition": f"attachment; filename=payments_export_{datetime.utcnow().strftime('%Y%m%d')}.csv"
            }
        )
    
    except Exception as e:
        print(f"Error exporting payments CSV: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

# ==================== ATTENDANCE EXPORT ====================

@export_router.get("/attendance/csv")
async def export_attendance_csv(
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    class_id: Optional[str] = None,
    current_user: dict = Depends(get_current_user)
):
    """Export attendance records to CSV"""
    try:
        # Build query
        query = {}
        
        if start_date and end_date:
            query["date"] = {
                "$gte": datetime.fromisoformat(start_date).date(),
                "$lte": datetime.fromisoformat(end_date).date()
            }
        
        if class_id:
            query["class_id"] = class_id
        
        attendance_records = await db.attendance.find(query).to_list(10000)
        
        # Create CSV
        output = io.StringIO()
        writer = csv.writer(output)
        
        # Header
        writer.writerow([
            "Date", "Child Name", "Class", "Status", "Coach Notes", "Marked By"
        ])
        
        # Data rows
        for record in attendance_records:
            child = await db.children.find_one({"id": record.get("child_id")})
            class_doc = await db.classes.find_one({"id": record.get("class_id")})
            
            writer.writerow([
                record.get("date", "").strftime("%Y-%m-%d") if hasattr(record.get("date"), "strftime") else str(record.get("date", "")),
                child.get("name", "") if child else "",
                f"{class_doc.get('day_of_week', '')} {class_doc.get('start_time', '')}" if class_doc else "",
                record.get("status", ""),
                record.get("coach_notes", ""),
                record.get("marked_by", "")
            ])
        
        csv_content = output.getvalue()
        output.close()
        
        return Response(
            content=csv_content,
            media_type="text/csv",
            headers={
                "Content-Disposition": f"attachment; filename=attendance_export_{datetime.utcnow().strftime('%Y%m%d')}.csv"
            }
        )
    
    except Exception as e:
        print(f"Error exporting attendance CSV: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

# ==================== LEADS EXPORT ====================

@export_router.get("/leads/csv")
async def export_leads_csv(
    status: Optional[str] = None,
    source: Optional[str] = None,
    current_user: dict = Depends(get_current_user)
):
    """Export leads to CSV"""
    try:
        # Build query
        query = {}
        if status:
            query["status"] = status
        if source:
            query["source"] = source
        
        leads = await db.leads.find(query).to_list(10000)
        
        # Create CSV
        output = io.StringIO()
        writer = csv.writer(output)
        
        # Header
        writer.writerow([
            "Name", "Phone", "Email", "Source", "Status", 
            "Preferred Center", "Created Date", "Notes"
        ])
        
        # Data rows
        for lead in leads:
            writer.writerow([
                lead.get("name", ""),
                lead.get("phone", ""),
                lead.get("email", ""),
                lead.get("source", ""),
                lead.get("status", ""),
                lead.get("preferred_centre", ""),
                lead.get("created_at", datetime.utcnow()).strftime("%Y-%m-%d") if isinstance(lead.get("created_at"), datetime) else "",
                lead.get("notes", "")
            ])
        
        csv_content = output.getvalue()
        output.close()
        
        return Response(
            content=csv_content,
            media_type="text/csv",
            headers={
                "Content-Disposition": f"attachment; filename=leads_export_{datetime.utcnow().strftime('%Y%m%d')}.csv"
            }
        )
    
    except Exception as e:
        print(f"Error exporting leads CSV: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

# ==================== COMPREHENSIVE REPORT ====================

@export_router.get("/comprehensive-report/pdf")
async def export_comprehensive_report(
    center_id: Optional[str] = None,
    current_user: dict = Depends(get_current_user)
):
    """Generate comprehensive business report PDF"""
    try:
        # Check authorization
        if current_user.get("role") not in ["admin", "franchise"]:
            raise HTTPException(status_code=403, detail="Not authorized")
        
        # Gather all data
        total_members = await db.users.count_documents({"role": "parent"})
        total_enrollments = await db.enrollments.count_documents({"status": "active"})
        
        payments = await db.payments.find({"status": "success"}).to_list(10000)
        total_revenue = sum(p.get("total_amount", 0) for p in payments)
        
        # Create PDF
        buffer = io.BytesIO()
        doc = SimpleDocTemplate(buffer, pagesize=A4)
        elements = []
        
        styles = getSampleStyleSheet()
        title_style = ParagraphStyle(
            'CustomTitle',
            parent=styles['Heading1'],
            fontSize=28,
            textColor=colors.HexColor('#FF1493'),
            spaceAfter=30,
            alignment=1
        )
        
        # Title
        elements.append(Paragraph("Tumble Gym - Comprehensive Business Report", title_style))
        elements.append(Paragraph(f"Generated: {datetime.utcnow().strftime('%Y-%m-%d %H:%M')}", styles['Normal']))
        elements.append(Spacer(1, 0.5 * inch))
        
        # Summary section
        elements.append(Paragraph("Executive Summary", styles['Heading2']))
        summary_data = [
            ["Metric", "Value"],
            ["Total Members", str(total_members)],
            ["Active Enrollments", str(total_enrollments)],
            ["Total Revenue", f"₹{total_revenue:,.2f}"],
            ["Average Revenue per Member", f"₹{total_revenue / max(total_members, 1):,.2f}"]
        ]
        
        summary_table = Table(summary_data)
        summary_table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#FF1493')),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
            ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('GRID', (0, 0), (-1, -1), 1, colors.black)
        ]))
        
        elements.append(summary_table)
        
        # Build PDF
        doc.build(elements)
        
        pdf_content = buffer.getvalue()
        buffer.close()
        
        return Response(
            content=pdf_content,
            media_type="application/pdf",
            headers={
                "Content-Disposition": f"attachment; filename=comprehensive_report_{datetime.utcnow().strftime('%Y%m%d')}.pdf"
            }
        )
    
    except Exception as e:
        print(f"Error generating comprehensive report: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))
