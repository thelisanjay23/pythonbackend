from jose import JWTError, jwt
from datetime import datetime, timedelta
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from passlib.context import CryptContext
from typing import Optional
import os
import random

SECRET_KEY = os.getenv("SECRET_KEY", "tumble-gym-secret-key-change-in-production")
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 60 * 24 * 30  # 30 days

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
security = HTTPBearer()

# In-memory OTP storage (replace with Redis in production)
otp_store = {}

def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verify a password against its hash"""
    return pwd_context.verify(plain_password, hashed_password)

def get_password_hash(password: str) -> str:
    """Hash a password"""
    return pwd_context.hash(password)

def create_access_token(data: dict, expires_delta: Optional[timedelta] = None):
    """Create JWT access token"""
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.utcnow() + expires_delta
    else:
        expire = datetime.utcnow() + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
    return encoded_jwt

def decode_token(token: str) -> dict:
    """Decode JWT token"""
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        return payload
    except JWTError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Could not validate credentials",
            headers={"WWW-Authenticate": "Bearer"},
        )

async def get_current_user(credentials: HTTPAuthorizationCredentials = Depends(security)):
    """Get current user from JWT token"""
    token = credentials.credentials
    payload = decode_token(token)
    user_id: str = payload.get("sub")
    if user_id is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Could not validate credentials",
        )
    return payload

def generate_otp() -> str:
    """Generate 6-digit OTP"""
    return str(random.randint(100000, 999999))

def store_otp(phone: str, otp: str, expires_in_minutes: int = 10):
    """Store OTP with expiration"""
    expires_at = datetime.utcnow() + timedelta(minutes=expires_in_minutes)
    otp_store[phone] = {
        "otp": otp,
        "expires_at": expires_at
    }

def verify_otp(phone: str, otp: str) -> bool:
    """Verify OTP"""
    if phone not in otp_store:
        return False
    
    stored_data = otp_store[phone]
    
    # Check expiration
    if datetime.utcnow() > stored_data["expires_at"]:
        del otp_store[phone]
        return False
    
    # Check OTP
    if stored_data["otp"] == otp:
        del otp_store[phone]  # Remove OTP after successful verification
        return True
    
    return False

def generate_referral_code(name: str) -> str:
    """Generate referral code from name"""
    import string
    clean_name = ''.join(c for c in name if c.isalnum())[:6].upper()
    random_suffix = ''.join(random.choices(string.digits, k=4))
    return f"{clean_name}{random_suffix}"

def generate_invoice_number() -> str:
    """Generate invoice number"""
    timestamp = datetime.utcnow().strftime("%Y%m%d%H%M%S")
    random_suffix = random.randint(100, 999)
    return f"TG-{timestamp}-{random_suffix}"
