from fastapi import FastAPI, APIRouter, HTTPException, Depends, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.encoders import jsonable_encoder
from motor.motor_asyncio import AsyncIOMotorClient
from dotenv import load_dotenv
from pathlib import Path
import os
import logging
from datetime import datetime, timedelta, date
from typing import List, Optional
from bson import ObjectId

# Import models and utilities
from models import *
from auth import (
    get_password_hash, verify_password, create_access_token,
    get_current_user, generate_otp, store_otp, verify_otp,
    generate_referral_code, generate_invoice_number
)
from razorpay_utils import (
    create_order, verify_payment_signature, calculate_amount,
    PLAN_PRICING, create_refund
)
from invoice_generator import generate_invoice_data
from pdf_generator import generate_pdf_invoice
from fastapi.responses import Response

ROOT_DIR = Path(__file__).parent
load_dotenv(ROOT_DIR / '.env')

# MongoDB connection
mongo_url = os.environ['MONGO_URL']
client = AsyncIOMotorClient(mongo_url)
db = client[os.environ['DB_NAME']]

# Create the main app
app = FastAPI(title="Tumble Gym API", version="1.0.0")

# Create API router with /api prefix
api_router = APIRouter(prefix="/api")

# Logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


#===================== DB Check ====================

@app.get("/api/db-check")
async def db_check():
    try:
        result = await db.command("ping")
        return {"connected": True, "result": result}
    except Exception as e:
        return {"connected": False, "error": str(e)}

# ==================== AUTHENTICATION ENDPOINTS ====================

@api_router.post("/auth/send-otp")
async def send_otp(request: OTPRequest):
    """Send OTP to phone number"""
    otp = generate_otp()
    store_otp(request.phone, otp)
    
    # TODO: Integrate with SMS gateway (Twilio/MSG91)
    logger.info(f"OTP for {request.phone}: {otp}")
    
    return {
        "success": True,
        "message": "OTP sent successfully",
        "dev_otp": otp  # Remove in production
    }

@api_router.post("/auth/verify-otp", response_model=TokenResponse)
async def verify_otp_endpoint(request: OTPVerify):
    """Verify OTP and login/register user"""
    if not verify_otp(request.phone, request.otp):
        raise HTTPException(status_code=400, detail="Invalid or expired OTP")
    
    # Check if user exists
    user_doc = await db.users.find_one({"phone": request.phone})
    
    if not user_doc:
        # Create new user
        new_user = User(
            phone=request.phone,
            name="",  # Will be updated in profile
            role=UserRole.PARENT,
            referral_code=generate_referral_code(request.phone)
        )
        user_dict = new_user.dict()
        await db.users.insert_one(user_dict)
        user = new_user
    else:
        user = User(**user_doc)
    
    # Create access token
    access_token = create_access_token(data={"sub": user.id, "role": user.role})
    
    return TokenResponse(
        access_token=access_token,
        user=user
    )

@api_router.post("/auth/register", response_model=TokenResponse)
async def register(user_data: UserCreate):
    """Register new user with username/password"""
    # Check if user exists
    existing = await db.users.find_one({"phone": user_data.phone})
    if existing:
        raise HTTPException(status_code=400, detail="Phone already registered")
    
    # Create user
    user = User(
        **user_data.dict(exclude={"password"}),
        referral_code=generate_referral_code(user_data.name)
    )
    user_dict = user.dict()
    user_dict["password"] = get_password_hash(user_data.password)
    
    await db.users.insert_one(user_dict)
    
    # Create token
    access_token = create_access_token(data={"sub": user.id, "role": user.role})
    
    return TokenResponse(access_token=access_token, user=user)

@api_router.post("/auth/login", response_model=TokenResponse)
async def login(credentials: UserLogin):
    """Login with phone and password"""
    user_doc = await db.users.find_one({"phone": credentials.phone})
    if not user_doc:
        raise HTTPException(status_code=404, detail="User not found")
    
    if "password" not in user_doc or not verify_password(credentials.password, user_doc["password"]):
        raise HTTPException(status_code=401, detail="Invalid credentials")
    
    user = User(**user_doc)
    access_token = create_access_token(data={"sub": user.id, "role": user.role})
    
    return TokenResponse(access_token=access_token, user=user)

@api_router.post("/auth/verify-mobile")
async def verify_mobile(request: dict):
    """Check if mobile number exists in DB"""
    # Accept either a dict body or an object with .phone attribute
    phone = request.get("phone") if isinstance(request, dict) else getattr(request, "phone", None)
    if not phone:
        raise HTTPException(status_code=400, detail="phone is required")
    user_doc = await db.users.find_one({"phone": phone})
    if not user_doc:
        return {
            "success": False,
            "message": "User not found",
            "user_exists": False
        }
    user = User(**user_doc)
    access_token = create_access_token(data={"sub": user.id, "role": user.role})
    return {
        "success": True,
        "message": "User exists",
        "user_exists": True,
        "access_token": access_token,
        "user": user
    }

@api_router.get("/auth/me", response_model=User)
async def get_me(current_user: dict = Depends(get_current_user)):
    """Get current user profile"""
    user_doc = await db.users.find_one({"id": current_user["sub"]})
    if not user_doc:
        raise HTTPException(status_code=404, detail="User not found")
    return User(**user_doc)

@api_router.patch("/auth/me")
async def update_user_profile(
    update_data: dict,
    current_user: dict = Depends(get_current_user)
):
    """Update user profile (name, emergency contact, additional info, consent)"""
    allowed_fields = ["name", "emergency_contact", "additional_info", "consent_accepted"]
    update_fields = {k: v for k, v in update_data.items() if k in allowed_fields}
    
    if not update_fields:
        raise HTTPException(status_code=400, detail="No valid fields to update")
    
    await db.users.update_one(
        {"id": current_user["sub"]},
        {"$set": update_fields}
    )
    
    return {"success": True, "updated_fields": list(update_fields.keys())}

@api_router.patch("/auth/me/default-center")
async def update_default_center(
    request: dict,
    current_user: dict = Depends(get_current_user)
):
    """Update user's default center preference"""
    center_id = request.get("center_id")
    if not center_id:
        raise HTTPException(status_code=400, detail="center_id is required")
    
    await db.users.update_one(
        {"id": current_user["sub"]},
        {"$set": {"default_center_id": center_id}}
    )
    return {"success": True, "default_center_id": center_id}

@api_router.get("/centers/my-centers")
async def get_user_centers(current_user: dict = Depends(get_current_user)):
    """Get centers linked to current user based on role"""
    role = current_user.get("role")
    user_id = current_user["sub"]
    
    if role == "admin" or role == "franchise":
        # Admins see all centers
        centers = await db.locations.find({}).to_list(100)
    elif role == "coach":
        # Coaches see their assigned centers
        # For now, return all centers (in production, filter by coach assignment)
        centers = await db.locations.find({}).to_list(100)
    elif role == "parent":
        # Parents see centers where their children are enrolled
        children = await db.children.find({"parent_id": user_id}).to_list(100)
        child_ids = [c["id"] for c in children]
        
        enrollments = await db.enrollments.find({"child_id": {"$in": child_ids}}).to_list(100)
        class_ids = list(set([e["class_id"] for e in enrollments]))
        
        classes = await db.classes.find({"id": {"$in": class_ids}}).to_list(100)
        location_ids = list(set([c["location_id"] for c in classes]))
        
        centers = await db.locations.find({"id": {"$in": location_ids}}).to_list(100)
        
        # If no enrollments, show all centers for browsing
        if not centers:
            centers = await db.locations.find({}).to_list(100)
    else:
        centers = await db.locations.find({}).to_list(100)
    
    return {"centers": [Location(**c) for c in centers]}

# ==================== PROGRAMS ENDPOINTS ====================

@api_router.get("/programs", response_model=List[Program])
async def get_programs(
    brand: Optional[BrandType] = None,
    level: Optional[str] = None
):
    """Get all programs with optional filters"""
    query = {}
    if brand:
        query["brand"] = brand
    if level:
        query["level"] = level
    
    programs = await db.programs.find(query).to_list(100)
    return [Program(**p) for p in programs]

@api_router.post("/programs", response_model=Program)
async def create_program(
    program: ProgramBase,
    current_user: dict = Depends(get_current_user)
):
    """Create new program (Admin only)"""
    if current_user.get("role") not in ["admin", "franchise"]:
        raise HTTPException(status_code=403, detail="Not authorized")
    
    new_program = Program(**program.dict())
    await db.programs.insert_one(new_program.dict())
    return new_program

# ==================== LOCATIONS ENDPOINTS ====================

@api_router.get("/locations", response_model=List[Location])
async def get_locations(city: Optional[str] = None):
    """Get all locations"""
    query = {}
    if city:
        query["city"] = city
    
    locations = await db.locations.find(query).to_list(100)
    return [Location(**loc) for loc in locations]

@api_router.post("/locations", response_model=Location)
async def create_location(
    location: LocationBase,
    current_user: dict = Depends(get_current_user)
):
    """Create new location (Admin only)"""
    if current_user.get("role") not in ["admin", "franchise"]:
        raise HTTPException(status_code=403, detail="Not authorized")
    
    new_location = Location(**location.dict())
    await db.locations.insert_one(new_location.dict())
    return new_location

# ==================== CLASSES ENDPOINTS ====================

@api_router.get("/classes", response_model=List[Class])
async def get_classes(
    program_id: Optional[str] = None,
    location_id: Optional[str] = None,
    coach_id: Optional[str] = None,
    day_of_week: Optional[str] = None
):
    """Get all classes with filters"""
    query = {}
    if program_id:
        query["program_id"] = program_id
    if location_id:
        query["location_id"] = location_id
    if coach_id:
        query["coach_id"] = coach_id
    if day_of_week:
        query["day_of_week"] = day_of_week
    
    classes = await db.classes.find(query).to_list(1000)
    return [Class(**c) for c in classes]

@api_router.post("/classes", response_model=Class)
async def create_class(
    class_data: ClassCreate,
    current_user: dict = Depends(get_current_user)
):
    """Create new class (Admin/Coach)"""
    if current_user.get("role") not in ["admin", "franchise", "coach"]:
        raise HTTPException(status_code=403, detail="Not authorized")
    
    new_class = Class(**class_data.dict())
    await db.classes.insert_one(new_class.dict())
    return new_class

# ==================== CHILDREN PROFILES ENDPOINTS ====================

@api_router.get("/children", response_model=List[ChildProfile])
async def get_children(current_user: dict = Depends(get_current_user)):
    """Get all children for current parent"""
    children = await db.children.find({"parent_id": current_user["sub"]}).to_list(100)
    return [ChildProfile(**child) for child in children]

@api_router.post("/children", response_model=ChildProfile)
async def create_child(
    child_data: ChildProfileBase,
    current_user: dict = Depends(get_current_user)
):
    """Create child profile"""
    new_child = ChildProfile(
        **child_data.dict(),
        parent_id=current_user["sub"]
    )
    # Convert date to datetime for MongoDB compatibility
    child_dict = new_child.dict()
    if isinstance(child_dict.get('dob'), date):
        child_dict['dob'] = datetime.combine(child_dict['dob'], datetime.min.time())
    await db.children.insert_one(child_dict)
    return new_child

@api_router.get("/children/{child_id}", response_model=ChildProfile)
async def get_child(
    child_id: str,
    current_user: dict = Depends(get_current_user)
):
    """Get specific child profile"""
    child = await db.children.find_one({"id": child_id, "parent_id": current_user["sub"]})
    if not child:
        raise HTTPException(status_code=404, detail="Child not found")
    return ChildProfile(**child)

# ==================== ENROLLMENTS ENDPOINTS ====================

@api_router.post("/enrollments", response_model=Enrollment)
async def create_enrollment(
    enrollment_data: EnrollmentCreate,
    current_user: dict = Depends(get_current_user)
):
    """Create new enrollment"""
    # Verify child belongs to user
    child = await db.children.find_one({"id": enrollment_data.child_id, "parent_id": current_user["sub"]})
    if not child:
        raise HTTPException(status_code=403, detail="Not authorized for this child")
    
    # Calculate end date based on plan
    plan_months = {"3_month": 3, "6_month": 6, "12_month": 12, "trial": 0}
    months = plan_months.get(enrollment_data.plan_type, 3)
    end_date = enrollment_data.start_date + timedelta(days=30 * months)
    
    new_enrollment = Enrollment(
        **enrollment_data.dict(),
        end_date=end_date
    )
    
    # Convert date fields to datetime for MongoDB compatibility
    enrollment_dict = new_enrollment.dict()
    if isinstance(enrollment_dict.get('start_date'), date):
        enrollment_dict['start_date'] = datetime.combine(enrollment_dict['start_date'], datetime.min.time())
    if isinstance(enrollment_dict.get('end_date'), date):
        enrollment_dict['end_date'] = datetime.combine(enrollment_dict['end_date'], datetime.min.time())
    
    await db.enrollments.insert_one(enrollment_dict)
    return new_enrollment

@api_router.get("/enrollments", response_model=List[Enrollment])
async def get_enrollments(
    child_id: Optional[str] = None,
    current_user: dict = Depends(get_current_user)
):
    """Get enrollments for user's children"""
    # Get user's children
    children = await db.children.find({"parent_id": current_user["sub"]}).to_list(100)
    child_ids = [c["id"] for c in children]
    
    query = {"child_id": {"$in": child_ids}}
    if child_id:
        query["child_id"] = child_id
    
    enrollments = await db.enrollments.find(query).to_list(100)
    return [Enrollment(**e) for e in enrollments]

@api_router.patch("/enrollments/{enrollment_id}/pause")
async def pause_enrollment(
    enrollment_id: str,
    current_user: dict = Depends(get_current_user)
):
    """Pause enrollment"""
    enrollment = await db.enrollments.find_one({"id": enrollment_id})
    if not enrollment:
        raise HTTPException(status_code=404, detail="Enrollment not found")
    
    # Verify ownership
    child = await db.children.find_one({"id": enrollment["child_id"], "parent_id": current_user["sub"]})
    if not child:
        raise HTTPException(status_code=403, detail="Not authorized")
    
    await db.enrollments.update_one(
        {"id": enrollment_id},
        {"$set": {"status": "paused"}}
    )
    
    return {"success": True, "message": "Enrollment paused"}

@api_router.patch("/enrollments/{enrollment_id}/resume")
async def resume_enrollment(
    enrollment_id: str,
    current_user: dict = Depends(get_current_user)
):
    """Resume enrollment"""
    enrollment = await db.enrollments.find_one({"id": enrollment_id})
    if not enrollment:
        raise HTTPException(status_code=404, detail="Enrollment not found")
    
    # Verify ownership
    child = await db.children.find_one({"id": enrollment["child_id"], "parent_id": current_user["sub"]})
    if not child:
        raise HTTPException(status_code=403, detail="Not authorized")
    
    await db.enrollments.update_one(
        {"id": enrollment_id},
        {"$set": {"status": "active"}}
    )
    
    return {"success": True, "message": "Enrollment resumed"}

# ==================== PAYMENTS ENDPOINTS ====================

@api_router.post("/payments/create-order")
async def create_payment_order(
    order_data: PaymentOrderCreate,
    current_user: dict = Depends(get_current_user)
):
    # log order_data 
    print("Order Data:", order_data)
    """Create Razorpay order for payment - updated to use child_id"""
    try:
        # Create temporary enrollment ID for payment tracking
        temp_enrollment_id = f"temp_{order_data.child_id}_{str(int(datetime.utcnow().timestamp()))}"
        
        # Create Razorpay order (receipt max 40 chars)
        receipt = f"pay_{order_data.child_id[:28]}"
        print(f"Creating Razorpay order - Amount: {order_data.amount}, Receipt: {receipt}")
        
        order_result = create_order(int(order_data.amount), receipt=receipt)
        print(f"Razorpay order result: {order_result}")
        
        if not order_result["success"]:
            error_msg = order_result.get("error", "Unknown error")
            logger.error(f"Razorpay order creation failed: {error_msg}")
            
            # Check if it's an authentication error
            if "Authentication failed" in error_msg or "authentication" in error_msg.lower():
                raise HTTPException(
                    status_code=500, 
                    detail="Razorpay authentication failed. Please check API credentials in .env file. See RAZORPAY_AUTH_ISSUE.md for troubleshooting."
                )
            
            raise HTTPException(status_code=500, detail=f"Razorpay error: {error_msg}")
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error creating payment order: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to create payment order: {str(e)}")
    
    # Create pending payment record
    payment = Payment(
        enrollment_id=temp_enrollment_id,  # Temporary, will be updated after verification
        amount=order_data.amount,
        tax_amount=order_data.amount * 0.18,  # 18% GST
        total_amount=order_data.amount,
        razorpay_order_id=order_result["order_id"],
        invoice_number=generate_invoice_number(),
        status="pending"
    )
    
    await db.payments.insert_one(payment.dict())
    
    # Store child_id and plan_type in payment metadata for later use
    await db.payments.update_one(
        {"id": payment.id},
        {"$set": {
            "child_id": order_data.child_id,
            "plan_type": order_data.plan_type
        }}
    )
    
    return {
        "order_id": order_result["order_id"],
        "amount": order_data.amount,
        "key_id": os.getenv("RAZORPAY_KEY_ID"),
        "payment_id": payment.id
    }

@api_router.post("/payments/verify")
async def verify_payment_endpoint(
    verify_data: PaymentVerify,
    current_user: dict = Depends(get_current_user)
):
    """Verify Razorpay payment and create enrollment"""
    # Get payment by order_id
    payment = await db.payments.find_one({"razorpay_order_id": verify_data.razorpay_order_id})
    if not payment:
        raise HTTPException(status_code=404, detail="Payment not found")
    
    # Verify signature
    is_valid = verify_payment_signature(
        verify_data.razorpay_order_id,
        verify_data.razorpay_payment_id,
        verify_data.razorpay_signature
    )
    
    if not is_valid:
        await db.payments.update_one(
            {"id": payment["id"]},
            {"$set": {"status": "failed"}}
        )
        raise HTTPException(status_code=400, detail="Payment verification failed")
    
    # Create enrollment after successful payment
    # Parse plan_type: "2day_6month" -> frequency: 2day, duration: 6 months
    plan_parts = verify_data.plan_type.split('_')
    frequency = plan_parts[0] if len(plan_parts) > 0 else "2day"
    duration_str = plan_parts[1] if len(plan_parts) > 1 else "3month"
    duration_months = int(duration_str.replace('month', ''))
    
    # Calculate enrollment dates
    start_date = datetime.utcnow()
    end_date = start_date + timedelta(days=duration_months * 30)
    
    # Get child details
    child = await db.children.find_one({"id": verify_data.child_id})
    if not child:
        raise HTTPException(status_code=404, detail="Child not found")
    
    # Get a default program (first program matching brand)
    # In production, let user select program
    program = await db.programs.find_one({"brand": child.get("brand", "Tumble Gym")})
    if not program:
        program = await db.programs.find_one({})  # Fallback to any program
    
    # Get a default class
    # In production, let user select class
    class_doc = await db.classes.find_one({})
    
    # Create enrollment
    enrollment = Enrollment(
        child_id=verify_data.child_id,
        program_id=program["id"] if program else "default_program",
        class_id=class_doc["id"] if class_doc else "default_class",
        parent_id=current_user["id"],
        start_date=start_date,
        end_date=end_date,
        status=EnrollmentStatus.ACTIVE,
        payment_status=PaymentStatus.SUCCESS
    )
    
    await db.enrollments.insert_one(enrollment.dict())
    
    # Update payment with enrollment_id
    await db.payments.update_one(
        {"id": payment["id"]},
        {"$set": {
            "enrollment_id": enrollment.id,
            "razorpay_payment_id": verify_data.razorpay_payment_id,
            "razorpay_signature": verify_data.razorpay_signature,
            "status": "success"
        }}
    )
    
    return {
        "success": True,
        "message": "Payment verified and enrollment created",
        "enrollment_id": enrollment.id,
        "payment_id": payment["id"]
    }
    
    # Update enrollment with payment
    await db.enrollments.update_one(
        {"id": payment["enrollment_id"]},
        {"$set": {"payment_id": payment_id, "status": "active"}}
    )
    
    return {
        "success": True,
        "message": "Payment verified successfully",
        "invoice_number": payment["invoice_number"]
    }

@api_router.get("/payments/my-payments", response_model=List[Payment])
async def get_my_payments(current_user: dict = Depends(get_current_user)):
    """Get all payments for current user"""
    # Get user's children
    children = await db.children.find({"parent_id": current_user["sub"]}).to_list(100)
    child_ids = [c["id"] for c in children]
    
    # Get enrollments
    enrollments = await db.enrollments.find({"child_id": {"$in": child_ids}}).to_list(100)
    enrollment_ids = [e["id"] for e in enrollments]
    
    # Get payments
    payments = await db.payments.find({"enrollment_id": {"$in": enrollment_ids}}).to_list(100)
    return [Payment(**p) for p in payments]

@api_router.get("/payments/{payment_id}/invoice")
async def get_invoice(
    payment_id: str,
    current_user: dict = Depends(get_current_user)
):
    """Generate and return invoice for a payment"""
    # Get payment
    payment = await db.payments.find_one({"id": payment_id})
    if not payment:
        raise HTTPException(status_code=404, detail="Payment not found")
    
    # Get enrollment
    enrollment = await db.enrollments.find_one({"id": payment.get("enrollment_id")})
    if not enrollment:
        raise HTTPException(status_code=404, detail="Enrollment not found")
    
    # Get child
    child = await db.children.find_one({"id": enrollment["child_id"]})
    if not child:
        raise HTTPException(status_code=404, detail="Child not found")
    
    # Get parent/user
    user = await db.users.find_one({"id": enrollment["parent_id"]})
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    
    # Verify ownership
    if user["id"] != current_user["sub"] and current_user["role"] not in ["admin", "franchise_owner"]:
        raise HTTPException(status_code=403, detail="Not authorized to view this invoice")
    
    # Get program and location details
    program = await db.programs.find_one({"id": enrollment.get("program_id", "")})
    location = await db.locations.find_one({"id": enrollment.get("center_id", "")}) if enrollment.get("center_id") else None
    
    # Generate invoice data
    invoice_data = generate_invoice_data(
        invoice_number=payment.get("invoice_number", f"INV-{payment['id'][:8].upper()}"),
        customer_name=user.get("name", "Customer"),
        customer_phone=user.get("phone", ""),
        customer_email=user.get("email", ""),
        customer_address=user.get("address", "Bangalore, India"),
        child_name=child.get("name", ""),
        program_name=program.get("name", "Fitness Program") if program else "Fitness Program",
        plan_type=payment.get("plan_type", "2day_6month"),
        base_amount=payment.get("amount", 0),
        start_date=enrollment.get("start_date", datetime.utcnow()),
        end_date=enrollment.get("end_date", datetime.utcnow() + timedelta(days=180)),
        center_name=location.get("name", "Tumble Gym Center") if location else "Tumble Gym Center",
        payment_id=payment.get("razorpay_payment_id", payment["id"]),
        payment_method="Razorpay" if payment.get("razorpay_payment_id") else "Online",
    )
    
    return invoice_data

@api_router.get("/payments/{payment_id}/invoice/pdf")
async def download_invoice_pdf(
    payment_id: str,
    current_user: dict = Depends(get_current_user)
):
    """Download invoice as PDF"""
    # Get invoice data (reuse the existing logic)
    payment = await db.payments.find_one({"id": payment_id})
    if not payment:
        raise HTTPException(status_code=404, detail="Payment not found")
    
    enrollment = await db.enrollments.find_one({"id": payment.get("enrollment_id")})
    if not enrollment:
        raise HTTPException(status_code=404, detail="Enrollment not found")
    
    child = await db.children.find_one({"id": enrollment["child_id"]})
    user = await db.users.find_one({"id": enrollment["parent_id"]})
    
    # Verify ownership
    if user["id"] != current_user["sub"] and current_user["role"] not in ["admin", "franchise_owner"]:
        raise HTTPException(status_code=403, detail="Not authorized")
    
    program = await db.programs.find_one({"id": enrollment.get("program_id", "")})
    location = await db.locations.find_one({"id": enrollment.get("center_id", "")}) if enrollment.get("center_id") else None
    
    # Generate invoice data
    invoice_data = generate_invoice_data(
        invoice_number=payment.get("invoice_number", f"INV-{payment['id'][:8].upper()}"),
        customer_name=user.get("name", "Customer"),
        customer_phone=user.get("phone", ""),
        customer_email=user.get("email", ""),
        customer_address=user.get("address", "Bangalore, India"),
        child_name=child.get("name", ""),
        program_name=program.get("name", "Fitness Program") if program else "Fitness Program",
        plan_type=payment.get("plan_type", "2day_6month"),
        base_amount=payment.get("amount", 0),
        start_date=enrollment.get("start_date", datetime.utcnow()),
        end_date=enrollment.get("end_date", datetime.utcnow() + timedelta(days=180)),
        center_name=location.get("name", "Tumble Gym Center") if location else "Tumble Gym Center",
        payment_id=payment.get("razorpay_payment_id", payment["id"]),
        payment_method="Razorpay" if payment.get("razorpay_payment_id") else "Online",
    )
    
    # Generate PDF
    pdf_bytes = generate_pdf_invoice(invoice_data)
    
    # Return PDF as downloadable file
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f"attachment; filename=invoice_{invoice_data['invoice_number']}.pdf"
        }
    )

@api_router.post("/payments/{payment_id}/invoice/email")
async def email_invoice(
    payment_id: str,
    current_user: dict = Depends(get_current_user)
):
    """Email invoice to customer"""
    # Get payment
    payment = await db.payments.find_one({"id": payment_id})
    if not payment:
        raise HTTPException(status_code=404, detail="Payment not found")
    
    # Get enrollment and user
    enrollment = await db.enrollments.find_one({"id": payment.get("enrollment_id")})
    user = await db.users.find_one({"id": enrollment["parent_id"]})
    
    # Verify ownership or admin
    if user["id"] != current_user["sub"] and current_user["role"] not in ["admin", "franchise_owner"]:
        raise HTTPException(status_code=403, detail="Not authorized")
    
    if not user.get("email"):
        raise HTTPException(status_code=400, detail="Customer email not found")
    
    # TODO: Implement email sending (using SendGrid, AWS SES, or SMTP)
    # For now, return success message
    return {
        "success": True,
        "message": f"Invoice will be sent to {user.get('email')}",
        "note": "Email functionality coming soon - integrate with SendGrid or AWS SES"
    }

# ==================== ATTENDANCE ENDPOINTS ====================

@api_router.post("/attendance", response_model=Attendance)
async def mark_attendance(
    attendance_data: AttendanceCreate,
    current_user: dict = Depends(get_current_user)
):
    """Mark attendance for a student (Coach only)"""
    if current_user.get("role") not in ["coach", "admin"]:
        raise HTTPException(status_code=403, detail="Not authorized")
    
    new_attendance = Attendance(
        **attendance_data.dict(),
        marked_by=current_user["sub"]
    )
    
    # Convert date fields to datetime for MongoDB compatibility
    attendance_dict = new_attendance.dict()
    if isinstance(attendance_dict.get('date'), date):
        attendance_dict['date'] = datetime.combine(attendance_dict['date'], datetime.min.time())
    
    await db.attendance.insert_one(attendance_dict)
    return new_attendance

@api_router.post("/attendance/bulk")
async def mark_bulk_attendance(
    bulk_data: BulkAttendanceCreate,
    current_user: dict = Depends(get_current_user)
):
    """Mark attendance for multiple students (Coach only)"""
    if current_user.get("role") not in ["coach", "admin"]:
        raise HTTPException(status_code=403, detail="Not authorized")
    
    attendance_records = []
    for item in bulk_data.attendance_list:
        attendance = Attendance(
            class_id=bulk_data.class_id,
            child_id=item["child_id"],
            date=bulk_data.date,
            status=item["status"],
            coach_notes=item.get("notes"),
            marked_by=current_user["sub"]
        )
        attendance_records.append(attendance.dict())
    
    if attendance_records:
        await db.attendance.insert_many(attendance_records)
    
    return {
        "success": True,
        "message": f"Marked attendance for {len(attendance_records)} students"
    }

@api_router.get("/attendance/my-child/{child_id}")
async def get_child_attendance(
    child_id: str,
    current_user: dict = Depends(get_current_user)
):
    """Get attendance for a specific child"""
    # Verify ownership
    child = await db.children.find_one({"id": child_id, "parent_id": current_user["sub"]})
    if not child:
        raise HTTPException(status_code=403, detail="Not authorized")
    
    attendance = await db.attendance.find({"child_id": child_id}).sort("date", -1).to_list(100)
    return [Attendance(**a) for a in attendance]

# ==================== ASSESSMENTS ENDPOINTS ====================

@api_router.post("/assessments", response_model=Assessment)
async def create_assessment(
    assessment_data: AssessmentCreate,
    current_user: dict = Depends(get_current_user)
):
    """Create skill assessment (Coach only)"""
    if current_user.get("role") not in ["coach", "admin"]:
        raise HTTPException(status_code=403, detail="Not authorized")
    
    new_assessment = Assessment(**assessment_data.dict())
    await db.assessments.insert_one(new_assessment.dict())
    return new_assessment

@api_router.get("/assessments/child/{child_id}")
async def get_child_assessments(
    child_id: str,
    current_user: dict = Depends(get_current_user)
):
    """Get all assessments for a child"""
    assessments = await db.assessments.find({"child_id": child_id}).to_list(100)
    return [Assessment(**a) for a in assessments]

# ==================== ADMIN DASHBOARD ENDPOINTS ====================

@api_router.get("/admin/dashboard")
async def get_dashboard_stats(current_user: dict = Depends(get_current_user)):
    """Get dashboard statistics (Admin only)"""
    if current_user.get("role") not in ["admin", "franchise"]:
        raise HTTPException(status_code=403, detail="Not authorized")
    
    # Count enrollments
    total_enrollments = await db.enrollments.count_documents({})
    active_enrollments = await db.enrollments.count_documents({"status": "active"})
    
    # Calculate revenue this month
    first_day = datetime.utcnow().replace(day=1, hour=0, minute=0, second=0)
    payments = await db.payments.find({
        "status": "success",
        "created_at": {"$gte": first_day}
    }).to_list(1000)
    revenue = sum(p["total_amount"] for p in payments)
    
    # Calculate attendance rate
    total_attendance = await db.attendance.count_documents({})
    present_count = await db.attendance.count_documents({"status": "present"})
    attendance_rate = (present_count / total_attendance * 100) if total_attendance > 0 else 0
    
    # Renewals due this week
    week_from_now = datetime.utcnow() + timedelta(days=7)
    renewals_due = await db.enrollments.count_documents({
        "end_date": {"$lte": week_from_now},
        "status": "active"
    })
    
    return DashboardStats(
        total_enrollments=total_enrollments,
        active_enrollments=active_enrollments,
        revenue_this_month=revenue,
        attendance_rate=round(attendance_rate, 2),
        renewals_due_this_week=renewals_due,
        trial_bookings_this_week=0  # TODO: Implement
    )

# ==================== LEADS ENDPOINTS ====================

@api_router.post("/leads", response_model=Lead)
async def create_lead(lead_data: LeadCreate):
    """Create new lead (Public endpoint for trial bookings)"""
    new_lead = Lead(**lead_data.dict())
    await db.leads.insert_one(new_lead.dict())
    
    # TODO: Send CRM webhook
    logger.info(f"New lead created: {new_lead.name} - {new_lead.phone}")
    
    return new_lead

# ==================== SEARCH ENDPOINT ====================

@api_router.get("/search")
async def search(q: str, current_user: dict = Depends(get_current_user)):
    """Search across programs, classes, and locations"""
    results = {
        "programs": [],
        "classes": [],
        "locations": []
    }
    
    # Search programs
    programs = await db.programs.find({
        "$or": [
            {"name": {"$regex": q, "$options": "i"}},
            {"description": {"$regex": q, "$options": "i"}}
        ]
    }).to_list(10)
    results["programs"] = [Program(**p) for p in programs]
    
    # Search locations
    locations = await db.locations.find({
        "$or": [
            {"name": {"$regex": q, "$options": "i"}},
            {"city": {"$regex": q, "$options": "i"}}
        ]
    }).to_list(10)
    results["locations"] = [Location(**loc) for loc in locations]
    
    return results

from ai_assistant import get_ai_response, get_quick_replies
import logging

# ==================== AI CHAT ASSISTANT ENDPOINTS ====================

logger = logging.getLogger(__name__)

class ChatMessage(BaseModel):
    message: str
    conversation_history: Optional[List[Dict[str, str]]] = None

@api_router.post("/chat")
async def chat_with_ai(chat_input: ChatMessage):
    """AI assistant for customer queries"""
    try:
        response = await get_ai_response(
            chat_input.message,
            chat_input.conversation_history
        )
        quick_replies = await get_quick_replies()
        
        return {
            "response": response,
            "quick_replies": quick_replies
        }
    except Exception as e:
        logger.error(f"AI chat error: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@api_router.get("/chat/quick-replies")
async def get_chat_quick_replies():
    """Get suggested quick reply options"""
    return {"quick_replies": await get_quick_replies()}

# Include router in main app
app.include_router(api_router)

# Include admin router
from admin_routes import admin_router
app.include_router(admin_router)

# Include curriculum routers
from curriculum_routes import curriculum_router, skills_router, feedback_router, coach_router
app.include_router(curriculum_router)
app.include_router(skills_router)
app.include_router(feedback_router)
app.include_router(coach_router)

# Include franchise router
from franchise_routes import franchise_router
app.include_router(franchise_router)

# Include package routes
from package_routes import package_router
app.include_router(package_router)

# Include social media routes
from social_media_routes import social_router
app.include_router(social_router)

# Include centers management routes
from centers_routes import centers_router
app.include_router(centers_router)

# Include AI insights routes
from ai_insights_routes import ai_insights_router
app.include_router(ai_insights_router)

# Include export routes
from export_routes import export_router
app.include_router(export_router)

# Include campaigns routes
from campaigns_routes import campaigns_router
app.include_router(campaigns_router)

# Include parent features routes
from parent_features_routes import parent_features_router
app.include_router(parent_features_router)

# Include phase 2 features routes
from phase2_features_routes import phase2_router
app.include_router(phase2_router)

# Include curriculum weekly routes
from curriculum_weekly_routes import curriculum_weekly_router
app.include_router(curriculum_weekly_router)

# Include coach features routes
from coach_features_routes import coach_router
app.include_router(coach_router)

# Include leads router
from leads_routes import leads_router, webhooks_router
app.include_router(leads_router)
app.include_router(webhooks_router)

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_credentials=True,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.on_event("shutdown")
async def shutdown_db_client():
    client.close()

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8001)