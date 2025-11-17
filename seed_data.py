"""
Seed script to populate initial data for Tumble Gym
Run with: python seed_data.py
"""
import asyncio
from motor.motor_asyncio import AsyncIOMotorClient
from dotenv import load_dotenv
import os
from pathlib import Path
from datetime import datetime, date
import uuid

ROOT_DIR = Path(__file__).parent
load_dotenv(ROOT_DIR / '.env')

# MongoDB connection
mongo_url = os.environ['MONGO_URL']
client = AsyncIOMotorClient(mongo_url)
db = client[os.environ['DB_NAME']]

async def seed_data():
    print("🌱 Seeding Tumble Gym database...")
    
    # Clear existing data
    print("Clearing existing data...")
    await db.programs.delete_many({})
    await db.locations.delete_many({})
    await db.classes.delete_many({})
    await db.skills.delete_many({})
    await db.users.delete_many({})
    
    # Seed Programs
    print("Seeding programs...")
    programs = [
        # TUMBLE GYM (Kids) - 5 Levels
        {
            "id": str(uuid.uuid4()),
            "name": "Tiny Tumblers (Level 1)",
            "brand": "tumble_gym",
            "level": "Level 1",
            "age_range": "1.5-3 years",
            "description": "Parent & Child Program (45 mins). Basic motor development, social engagement, parent-child bonding through music & movement. Builds body awareness, balance, and confidence.",
            "duration_weeks": 12,
            "created_at": datetime.utcnow()
        },
        {
            "id": str(uuid.uuid4()),
            "name": "Little Movers (Level 2)",
            "brand": "tumble_gym",
            "level": "Level 2",
            "age_range": "3-5 years",
            "description": "Preschool Independence (50 mins). Balance beam walks, trampoline jumps, rolling, hanging, core strength. Enhances gross motor skills, attention span, and prepares for structured learning.",
            "duration_weeks": 12,
            "created_at": datetime.utcnow()
        },
        {
            "id": str(uuid.uuid4()),
            "name": "Junior Gym Stars (Level 3)",
            "brand": "tumble_gym",
            "level": "Level 3",
            "age_range": "5-7 years",
            "description": "Skill Foundation (60 mins). Gymnastics basics - cartwheels, handstands, forward/backward rolls, core & upper body strength. Improves posture, balance, coordination, and builds confidence.",
            "duration_weeks": 12,
            "created_at": datetime.utcnow()
        },
        {
            "id": str(uuid.uuid4()),
            "name": "Tumble Champs (Level 4)",
            "brand": "tumble_gym",
            "level": "Level 4",
            "age_range": "7-10 years",
            "description": "Skill Progression (60-75 mins). Intermediate gymnastics - round-offs, bridges, apparatus training (bars, beams, vault). Encourages goal setting, enhances muscle tone & flexibility.",
            "duration_weeks": 12,
            "created_at": datetime.utcnow()
        },
        {
            "id": str(uuid.uuid4()),
            "name": "Tumble Pro (Level 5)",
            "brand": "tumble_gym",
            "level": "Level 5",
            "age_range": "10-14 years",
            "description": "Advanced Skills (75 mins). Tumbling sequences, flips (intro-level), strength & conditioning circuits, team routines. Builds peak physical strength, discipline, and leadership.",
            "duration_weeks": 12,
            "created_at": datetime.utcnow()
        },
        
        # TUMBLE FIT (Adults)
        {
            "id": str(uuid.uuid4()),
            "name": "Fit Basics",
            "brand": "tumble_fit",
            "level": "Foundation",
            "age_range": "15-45 years",
            "description": "Foundation Level (60 mins). Mobility & flexibility drills, core and posture correction, handstand prep. Rebuilds functional strength, improves joint health & endurance.",
            "duration_weeks": 12,
            "created_at": datetime.utcnow()
        },
        {
            "id": str(uuid.uuid4()),
            "name": "Tumble HIIT",
            "brand": "tumble_fit",
            "level": "Advanced",
            "age_range": "15-45 years",
            "description": "Gymnastics-Based Cardio (45-60 mins). High-intensity circuit training, plyometrics, bodyweight strength, balance drills. Fat burn + full body toning, improves balance & agility.",
            "duration_weeks": 12,
            "created_at": datetime.utcnow()
        },
        {
            "id": str(uuid.uuid4()),
            "name": "Mobility & Flex",
            "brand": "tumble_fit",
            "level": "Intermediate",
            "age_range": "15-45 years",
            "description": "Flexibility Program (60 mins). Deep mobility stretches, strength-through-range training, injury prevention. Improves posture, flexibility, and reduces stress.",
            "duration_weeks": 12,
            "created_at": datetime.utcnow()
        },
        
        # TUMBLE GOLD (Seniors 50+)
        {
            "id": str(uuid.uuid4()),
            "name": "Gentle Move (Level 1)",
            "brand": "tumble_gold",
            "level": "Level 1",
            "age_range": "50+ years",
            "description": "Gentle Movement. Chair exercises, assisted stretches, light resistance bands. Improves joint mobility, reduces stiffness, boosts circulation. Perfect for beginners.",
            "duration_weeks": 12,
            "created_at": datetime.utcnow()
        },
        {
            "id": str(uuid.uuid4()),
            "name": "Active Gold (Level 2)",
            "brand": "tumble_gold",
            "level": "Level 2",
            "age_range": "50+ years",
            "description": "Core Strength & Posture. Balance beams (low height), resistance circuits, coordination games. Builds movement confidence, prevents falls, increases stamina.",
            "duration_weeks": 12,
            "created_at": datetime.utcnow()
        },
        {
            "id": str(uuid.uuid4()),
            "name": "Vital Gold (Level 3)",
            "brand": "tumble_gold",
            "level": "Level 3",
            "age_range": "50+ years",
            "description": "Functional Movement & Longevity. Strength + balance flows, yoga-gymnastics hybrid drills, light weights. Enhances energy, confidence, and independence.",
            "duration_weeks": 12,
            "created_at": datetime.utcnow()
        },
    ]
    await db.programs.insert_many(programs)
    print(f"✅ Created {len(programs)} programs")
    
    # Seed Locations
    print("Seeding locations...")
    locations = [
        {
            "id": str(uuid.uuid4()),
            "name": "Tumble Gym Hennur (Kothanur)",
            "city": "Bangalore",
            "address": "Indradhanush, Adidas Building, Basement No.15, 50/5 Hennur Bagalur Main Rd, Kothanur Post Narayanapura, Kothanur, Bangalore - 560077",
            "lat": 13.0358,
            "lng": 77.6394,
            "phone": "+91 8867914814",
            "whatsapp": "+91 9606023971",
            "gstin": "29AABCT1234H1Z5",
            "created_at": datetime.utcnow()
        },
        {
            "id": str(uuid.uuid4()),
            "name": "Tumble Gym Mysuru",
            "city": "Mysuru",
            "address": "37F, First Floor, 1st Main Rd, opposite MUDA Ground, 1st Stage, Vijayanagar, Mysuru, Karnataka - 570017",
            "lat": 12.3051,
            "lng": 76.6553,
            "phone": "+91 8618684685",
            "whatsapp": "+91 9606023972",
            "gstin": "29AABCT1234H1Z6",
            "created_at": datetime.utcnow()
        },
        {
            "id": str(uuid.uuid4()),
            "name": "Tumble Gym Banashankari",
            "city": "Bangalore",
            "address": "1st Floor, 80 Feet Road, BDA Girinagar 4th Phase, Banashankari 3rd Stage, Bangalore - 560085",
            "lat": 12.9250,
            "lng": 77.5540,
            "phone": "+91 7019271281",
            "whatsapp": "+91 9606023971",
            "gstin": "29AABCT1234H1Z7",
            "created_at": datetime.utcnow()
        },
        {
            "id": str(uuid.uuid4()),
            "name": "Tumble Gym Electronic City",
            "city": "Bangalore",
            "address": "Above Moments Fitness Hub, Electronic City, Bangalore - 560100",
            "lat": 12.8458,
            "lng": 77.6603,
            "phone": "+91 9606023971",
            "whatsapp": "+91 9606023971",
            "gstin": "29AABCT1234H1Z8",
            "created_at": datetime.utcnow()
        }
    ]
    await db.locations.insert_many(locations)
    print(f"✅ Created {len(locations)} locations")
    
    # Seed Demo Coach User
    print("Seeding demo users...")
    from auth import get_password_hash
    
    demo_users = [
        {
            "id": str(uuid.uuid4()),
            "phone": "9999999999",
            "email": "coach@tumblegym.com",
            "name": "Coach Priya",
            "role": "coach",
            "password": get_password_hash("coach123"),
            "created_at": datetime.utcnow(),
            "referral_code": "COACH001"
        },
        {
            "id": str(uuid.uuid4()),
            "phone": "8888888888",
            "email": "admin@tumblegym.com",
            "name": "Admin Raj",
            "role": "admin",
            "password": get_password_hash("admin123"),
            "created_at": datetime.utcnow(),
            "referral_code": "ADMIN001"
        },
        {
            "id": str(uuid.uuid4()),
            "phone": "7019271281",
            "email": "support@tumblegym.com",
            "name": "Support Admin",
            "role": "admin",
            "password": get_password_hash("support123"),
            "created_at": datetime.utcnow(),
            "referral_code": "SUPPORT001"
        }
    ]
    await db.users.insert_many(demo_users)
    print(f"✅ Created {len(demo_users)} demo users")
    
    # Seed Classes
    print("Seeding classes...")
    classes = []
    days = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday"]
    times = [("10:00", "11:00"), ("11:30", "12:30"), ("16:00", "17:00"), ("17:30", "18:30")]
    
    for location in locations:
        for program in programs[:3]:  # First 3 programs (kids programs)
            for day in days[:3]:  # Mon, Tue, Wed
                for start_time, end_time in times[:2]:  # Morning and evening slots
                    class_obj = {
                        "id": str(uuid.uuid4()),
                        "program_id": program["id"],
                        "location_id": location["id"],
                        "coach_id": demo_users[0]["id"],  # Coach Priya
                        "day_of_week": day,
                        "start_time": start_time,
                        "end_time": end_time,
                        "capacity": 20,
                        "created_at": datetime.utcnow()
                    }
                    classes.append(class_obj)
    
    if classes:
        await db.classes.insert_many(classes)
    print(f"✅ Created {len(classes)} classes")
    
    # Seed Skills
    print("Seeding skills...")
    skills = [
        # Kids Skills
        {
            "id": str(uuid.uuid4()),
            "program_id": programs[0]["id"],
            "name": "Forward Roll",
            "description": "Basic forward somersault",
            "level": 1
        },
        {
            "id": str(uuid.uuid4()),
            "program_id": programs[0]["id"],
            "name": "Balance Beam Walk",
            "description": "Walk across low balance beam",
            "level": 1
        },
        {
            "id": str(uuid.uuid4()),
            "program_id": programs[1]["id"],
            "name": "Cartwheel",
            "description": "Side-over cartwheel",
            "level": 2
        },
        {
            "id": str(uuid.uuid4()),
            "program_id": programs[1]["id"],
            "name": "Handstand (Wall)",
            "description": "Handstand against wall for 10 seconds",
            "level": 2
        },
        {
            "id": str(uuid.uuid4()),
            "program_id": programs[2]["id"],
            "name": "Round-off",
            "description": "Round-off back handspring entry",
            "level": 3
        },
    ]
    await db.skills.insert_many(skills)
    print(f"✅ Created {len(skills)} skills")
    
    print("\n🎉 Database seeded successfully!")
    print("\n📝 Demo Credentials:")
    print("   Coach Login: 9999999999 / coach123")
    print("   Admin Login: 8888888888 / admin123")
    print("\n   For Parent: Use OTP login with any phone number")
    
    client.close()

if __name__ == "__main__":
    asyncio.run(seed_data())
