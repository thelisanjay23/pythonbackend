from pydantic import BaseModel, Field, EmailStr
from typing import List, Optional, Dict, Any
from datetime import datetime, date
from enum import Enum

# Enums
class UserRole(str, Enum):
    PARENT = "parent"
    COACH = "coach"
    ADMIN = "admin"
    FRANCHISE = "franchise"

class BrandType(str, Enum):
    TUMBLE_GYM = "tumble_gym"  # Kids
    TUMBLE_FIT = "tumble_fit"  # Adults
    TUMBLE_GOLD = "tumble_gold"  # Seniors 50+

class PlanType(str, Enum):
    TRIAL = "trial"
    THREE_MONTH = "3_month"  # ₹12,000
    SIX_MONTH = "6_month"  # ₹18,000
    TWELVE_MONTH = "12_month"  # ₹32,000

class EnrollmentStatus(str, Enum):
    ACTIVE = "active"
    PAUSED = "paused"
    EXPIRED = "expired"
    CANCELLED = "cancelled"

class AttendanceStatus(str, Enum):
    PRESENT = "present"
    ABSENT = "absent"
    LATE = "late"
    MAKEUP = "makeup"
    TRIAL = "trial"

class SkillProgressStage(str, Enum):
    ATTEMPTED = "attempted"
    ASSISTED = "assisted"
    INDEPENDENT = "independent"
    MASTERED = "mastered"

class SkillCategory(str, Enum):
    FLOOR = "floor"
    BEAM = "beam"
    BAR = "bar"
    VAULT = "vault"
    COORDINATION = "coordination"
    FLEXIBILITY = "flexibility"

class PaymentStatus(str, Enum):
    PENDING = "pending"
    SUCCESS = "success"
    FAILED = "failed"
    REFUNDED = "refunded"

# User Models
class UserBase(BaseModel):
    phone: str
    email: Optional[EmailStr] = None
    name: str
    role: UserRole
    default_center_id: Optional[str] = None  # User's preferred center

class UserCreate(UserBase):
    password: str

class UserLogin(BaseModel):
    phone: str
    password: str

class User(UserBase):
    id: str = Field(default_factory=lambda: str(__import__('uuid').uuid4()))
    created_at: datetime = Field(default_factory=datetime.utcnow)
    gstin: Optional[str] = None  # For GST invoices
    referral_code: Optional[str] = None
    emergency_contact: Optional[str] = None  # Emergency contact number
    additional_info: Optional[str] = None  # Any additional information
    consent_accepted: Optional[bool] = False  # Terms and conditions consent

# OTP Models
class OTPRequest(BaseModel):
    phone: str

class OTPVerify(BaseModel):
    phone: str
    otp: str

# Child/Member Profile Models
class ChildProfileBase(BaseModel):
    name: str
    dob: date
    age_group: str  # "3-5", "6-8", "9-12", etc.
    medical_notes: Optional[str] = None
    photo_consent: bool = False
    media_consent: bool = False

class ChildProfileCreate(ChildProfileBase):
    parent_id: str

class ChildProfile(ChildProfileBase):
    id: str = Field(default_factory=lambda: str(__import__('uuid').uuid4()))
    parent_id: str
    created_at: datetime = Field(default_factory=datetime.utcnow)

# Program Models
class ProgramBase(BaseModel):
    name: str
    brand: BrandType
    level: str  # "Level 1", "Level 2", etc.
    age_range: str  # "3-5 years", "18-35 years", "50+ years"
    description: str
    duration_weeks: int = 12

class Program(ProgramBase):
    id: str = Field(default_factory=lambda: str(__import__('uuid').uuid4()))
    created_at: datetime = Field(default_factory=datetime.utcnow)

# Location Models
class LocationBase(BaseModel):
    name: str
    city: str
    address: str
    lat: Optional[float] = None
    lng: Optional[float] = None
    phone: str
    whatsapp: Optional[str] = None
    gstin: Optional[str] = None  # For invoicing

class Location(LocationBase):
    id: str = Field(default_factory=lambda: str(__import__('uuid').uuid4()))
    created_at: datetime = Field(default_factory=datetime.utcnow)

# Class Models
class ClassBase(BaseModel):
    program_id: str
    location_id: str
    coach_id: str
    day_of_week: str  # "Monday", "Wednesday", etc.
    start_time: str  # "17:00"
    end_time: str  # "18:00"
    capacity: int = 20

class ClassCreate(ClassBase):
    pass

class Class(ClassBase):
    id: str = Field(default_factory=lambda: str(__import__('uuid').uuid4()))
    created_at: datetime = Field(default_factory=datetime.utcnow)

# Enrollment Models
class EnrollmentBase(BaseModel):
    child_id: str
    class_id: str
    plan_type: PlanType
    start_date: date
    auto_renew: bool = False

class EnrollmentCreate(EnrollmentBase):
    coupon_code: Optional[str] = None

class Enrollment(EnrollmentBase):
    id: str = Field(default_factory=lambda: str(__import__('uuid').uuid4()))
    end_date: date
    status: EnrollmentStatus = EnrollmentStatus.ACTIVE
    makeup_credits: int = 0
    payment_id: Optional[str] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)

# Attendance Models
class AttendanceBase(BaseModel):
    class_id: str
    child_id: str
    date: date
    status: AttendanceStatus

class AttendanceCreate(AttendanceBase):
    coach_notes: Optional[str] = None

class Attendance(AttendanceBase):
    id: str = Field(default_factory=lambda: str(__import__('uuid').uuid4()))
    coach_notes: Optional[str] = None
    marked_by: str  # coach_id
    created_at: datetime = Field(default_factory=datetime.utcnow)

class BulkAttendanceCreate(BaseModel):
    class_id: str
    date: date
    attendance_list: List[Dict[str, Any]]  # [{child_id, status, notes}]

# Payment Models
class PaymentOrderCreate(BaseModel):
    child_id: str  # Changed from enrollment_id to child_id
    amount: float
    plan_type: str  # Changed from PlanType to str for flexibility
    coupon_code: Optional[str] = None

class PaymentVerify(BaseModel):
    razorpay_order_id: str
    razorpay_payment_id: str
    razorpay_signature: str
    child_id: str
    plan_type: str
    amount: float

class Payment(BaseModel):
    id: str = Field(default_factory=lambda: str(__import__('uuid').uuid4()))
    enrollment_id: str
    amount: float
    tax_amount: float
    total_amount: float
    razorpay_order_id: Optional[str] = None
    razorpay_payment_id: Optional[str] = None
    razorpay_signature: Optional[str] = None
    status: PaymentStatus = PaymentStatus.PENDING
    invoice_number: Optional[str] = None
    invoice_pdf_url: Optional[str] = None
    gstin: Optional[str] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)

# Skill & Assessment Models
class SkillBase(BaseModel):
    program_id: str
    name: str
    description: str
    level: int  # 1, 2, 3, etc.

class Skill(SkillBase):
    id: str = Field(default_factory=lambda: str(__import__('uuid').uuid4()))

class AssessmentBase(BaseModel):
    child_id: str
    skill_id: str
    achieved: bool
    coach_notes: Optional[str] = None

class AssessmentCreate(AssessmentBase):
    coach_id: str

class Assessment(AssessmentBase):
    id: str = Field(default_factory=lambda: str(__import__('uuid').uuid4()))
    coach_id: str
    assessed_on: datetime = Field(default_factory=datetime.utcnow)

# Announcement Models
class AnnouncementBase(BaseModel):
    title: str
    message: str
    audience: str  # "all", "parents", "coaches", "location:xyz", "class:abc"
    channels: List[str]  # ["push", "whatsapp", "email"]

class AnnouncementCreate(AnnouncementBase):
    created_by: str  # admin_id

class Announcement(AnnouncementBase):
    id: str = Field(default_factory=lambda: str(__import__('uuid').uuid4()))
    created_by: str
    sent_at: datetime = Field(default_factory=datetime.utcnow)

# Lead Models
class LeadBase(BaseModel):
    name: str
    phone: str
    email: Optional[EmailStr] = None
    source: str  # "website", "referral", "walk-in"
    brand_interest: BrandType
    location_id: Optional[str] = None

class LeadCreate(LeadBase):
    utm_source: Optional[str] = None
    utm_campaign: Optional[str] = None
    referral_code: Optional[str] = None

class Lead(LeadBase):
    id: str = Field(default_factory=lambda: str(__import__('uuid').uuid4()))
    status: str = "new"  # "new", "contacted", "trial_booked", "enrolled", "lost"
    trial_date: Optional[datetime] = None
    notes: Optional[str] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)

# Coupon Models
class CouponBase(BaseModel):
    code: str
    discount_type: str  # "percentage", "fixed"
    discount_value: float
    max_redemptions: int
    valid_from: date
    valid_to: date
    locations: Optional[List[str]] = None  # location_ids

class Coupon(CouponBase):
    id: str = Field(default_factory=lambda: str(__import__('uuid').uuid4()))
    redemptions: int = 0
    created_at: datetime = Field(default_factory=datetime.utcnow)

# Response Models
class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: User

class DashboardStats(BaseModel):
    total_enrollments: int
    active_enrollments: int
    revenue_this_month: float
    attendance_rate: float
    renewals_due_this_week: int
    trial_bookings_this_week: int

class ChildProgress(BaseModel):
    child_id: str
    child_name: str
    total_sessions: int
    attended_sessions: int
    attendance_rate: float
    skills_achieved: List[Dict[str, Any]]
    recent_feedback: List[Dict[str, Any]]

# Coach Management Models
class CoachProfile(BaseModel):
    id: str
    name: str
    phone: str
    email: Optional[EmailStr] = None
    specializations: List[str] = []  # ["tumble_gym", "tumble_fit"]
    assigned_locations: List[str] = []  # location_ids
    active: bool = True
    rating: float = 0.0
    total_classes: int = 0
    punctuality_score: float = 100.0
    created_at: datetime = Field(default_factory=datetime.utcnow)

# Offer/Campaign Models
class OfferBase(BaseModel):
    title: str
    description: str
    discount_type: str  # "percentage", "fixed", "bogo"
    discount_value: float
    applicable_plans: List[str]  # ["3_month", "6_month"]
    locations: Optional[List[str]] = None
    brands: Optional[List[str]] = None
    valid_from: date
    valid_to: date
    max_redemptions: Optional[int] = None

class Offer(OfferBase):
    id: str = Field(default_factory=lambda: str(__import__('uuid').uuid4()))
    redemptions: int = 0
    created_by: str
    created_at: datetime = Field(default_factory=datetime.utcnow)

# Communication Campaign Models
class CampaignBase(BaseModel):
    name: str
    message_template: str
    audience_filter: Dict[str, Any]  # {"role": "parent", "location_id": "xyz"}
    channels: List[str]  # ["push", "whatsapp", "email", "sms"]
    schedule_type: str  # "immediate", "scheduled", "recurring"
    schedule_time: Optional[datetime] = None

class Campaign(CampaignBase):
    id: str = Field(default_factory=lambda: str(__import__('uuid').uuid4()))
    status: str = "draft"  # "draft", "scheduled", "sent", "failed"
    sent_count: int = 0
    delivered_count: int = 0
    opened_count: int = 0
    created_by: str
    created_at: datetime = Field(default_factory=datetime.utcnow)

# Enhanced Dashboard Stats Models
class EnhancedDashboardStats(BaseModel):
    # Overview
    total_enrollments: int
    active_enrollments: int
    paused_enrollments: int
    expired_enrollments: int
    
    # Revenue
    revenue_today: float
    revenue_this_week: float
    revenue_this_month: float
    revenue_by_centre: Dict[str, float]
    
    # Attendance
    attendance_today_percentage: float
    attendance_this_week_percentage: float
    missed_classes_today: int
    
    # Renewals
    renewals_due_7_days: int
    renewals_due_30_days: int
    renewal_conversion_rate: float
    
    # Coaches
    total_active_coaches: int
    coaches_on_duty_today: int
    
    # Occupancy
    overall_occupancy_percentage: float
    classes_today: int
    classes_this_week: int
    
    # Alerts
    recent_announcements: List[Dict[str, Any]]
    pending_actions: int

# Member Details Model
class MemberDetails(BaseModel):
    member_id: str
    parent_name: str
    parent_phone: str
    parent_email: Optional[str]
    children: List[Dict[str, Any]]
    active_enrollments: List[Dict[str, Any]]
    attendance_summary: Dict[str, Any]
    payment_history: List[Dict[str, Any]]
    makeup_credits: int
    total_spent: float
    join_date: datetime
    last_visit: Optional[datetime]

# Class Schedule Details
class ClassScheduleDetail(BaseModel):
    id: str
    program_name: str
    level: str
    location_name: str
    coach_name: str
    day_of_week: str
    start_time: str
    end_time: str
    capacity: int
    enrolled_count: int
    occupancy_percentage: float
    waitlist_count: int = 0

# Reports Models
class ReportFilter(BaseModel):
    start_date: Optional[date] = None
    end_date: Optional[date] = None
    centre_ids: Optional[List[str]] = None
    program_ids: Optional[List[str]] = None
    brand: Optional[str] = None

class EnrollmentReport(BaseModel):
    total_enrollments: int
    new_enrollments: int
    renewals: int
    cancellations: int
    by_plan: Dict[str, int]
    by_brand: Dict[str, int]
    by_centre: Dict[str, int]
    trend_data: List[Dict[str, Any]]

class RevenueReport(BaseModel):
    total_revenue: float
    by_centre: Dict[str, float]
    by_plan: Dict[str, float]
    by_payment_method: Dict[str, float]
    refunds: float
    net_revenue: float
    trend_data: List[Dict[str, Any]]

class AttendanceReport(BaseModel):
    total_sessions: int
    attended_sessions: int
    absent_sessions: int
    makeup_sessions: int
    attendance_rate: float
    by_centre: Dict[str, float]
    by_program: Dict[str, float]
    by_day: Dict[str, int]


# Curriculum & Skills Models
class CurriculumLevel(BaseModel):
    id: str = Field(default_factory=lambda: str(__import__('uuid').uuid4()))
    program: str  # "tumble_gym", "tumble_fit", "tumble_gold"
    level_name: str  # "Tiny Tumblers", "Little Movers", etc.
    age_group: str  # "1.5-3 yrs"
    focus_area: str  # "Parent-child interaction, motor skills"
    order: int  # 1, 2, 3...
    description: Optional[str] = None
    badge_image: Optional[str] = None

class Skill(BaseModel):
    id: str = Field(default_factory=lambda: str(__import__('uuid').uuid4()))
    level_id: str
    category: SkillCategory
    name: str  # "Forward Roll", "Handstand"
    description: Optional[str] = None
    video_demo_url: Optional[str] = None
    order: int  # Display order within category

class SkillProgress(BaseModel):
    id: str = Field(default_factory=lambda: str(__import__('uuid').uuid4()))
    child_id: str
    skill_id: str
    stage: SkillProgressStage = SkillProgressStage.ATTEMPTED
    coach_id: str
    notes: Optional[str] = None
    media_url: Optional[str] = None  # Photo/video of performance
    assessment_date: date = Field(default_factory=lambda: datetime.utcnow().date())
    updated_at: datetime = Field(default_factory=datetime.utcnow)

class Badge(BaseModel):
    id: str = Field(default_factory=lambda: str(__import__('uuid').uuid4()))
    name: str  # "Balance Star", "Cartwheel Hero"
    description: str
    icon: str  # Icon name or URL
    criteria: Dict[str, Any]  # {"skills_mastered": 5, "category": "floor"}
    level_id: Optional[str] = None

class ChildBadge(BaseModel):
    id: str = Field(default_factory=lambda: str(__import__('uuid').uuid4()))
    child_id: str
    badge_id: str
    earned_date: date = Field(default_factory=lambda: datetime.utcnow().date())
    awarded_by: str  # coach_id

# Enhanced Attendance with trial and makeup
class AttendanceCreate(BaseModel):
    child_id: str
    class_id: str
    date: date
    status: AttendanceStatus
    notes: Optional[str] = None
    is_makeup: bool = False
    is_trial: bool = False

# Coach Attendance & Check-in
class CoachCheckIn(BaseModel):
    id: str = Field(default_factory=lambda: str(__import__('uuid').uuid4()))
    coach_id: str
    location_id: str
    check_in_time: datetime = Field(default_factory=datetime.utcnow)
    check_out_time: Optional[datetime] = None
    checkin_date: date = Field(default_factory=lambda: datetime.utcnow().date())
    notes: Optional[str] = None

# Replacement Request
class ReplacementRequest(BaseModel):
    id: str = Field(default_factory=lambda: str(__import__('uuid').uuid4()))
    requester_coach_id: str
    class_id: str
    request_date: date
    reason: str
    replacement_coach_id: Optional[str] = None
    status: str = "pending"  # pending, approved, rejected, filled
    created_at: datetime = Field(default_factory=datetime.utcnow)
    resolved_at: Optional[datetime] = None

# Feedback Module
class FeedbackBase(BaseModel):
    child_id: str
    coach_id: str
    class_id: Optional[str] = None
    period: str  # "weekly", "monthly", "session"
    strengths: str
    focus_areas: str
    next_goals: str
    overall_rating: int  # 1-5
    media_urls: List[str] = []

class Feedback(FeedbackBase):
    id: str = Field(default_factory=lambda: str(__import__('uuid').uuid4()))
    status: str = "draft"  # draft, submitted, approved, shared
    approved_by: Optional[str] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)
    approved_at: Optional[datetime] = None

# Media Upload
class MediaUpload(BaseModel):
    id: str = Field(default_factory=lambda: str(__import__('uuid').uuid4()))
    child_id: str
    coach_id: str
    skill_id: Optional[str] = None
    media_type: str  # "photo", "video"
    url: str
    thumbnail_url: Optional[str] = None
    caption: Optional[str] = None
    approved: bool = False
    approved_by: Optional[str] = None
    uploaded_at: datetime = Field(default_factory=datetime.utcnow)

