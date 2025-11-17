"""
Database Migration Script - Fix Date Encoding Issues
Run this to convert all date objects to datetime for BSON compatibility
"""
import asyncio
from motor.motor_asyncio import AsyncIOMotorClient
from dotenv import load_dotenv
import os
from pathlib import Path
from datetime import datetime, date

ROOT_DIR = Path(__file__).parent
load_dotenv(ROOT_DIR / '.env')

mongo_url = os.environ['MONGO_URL']
client = AsyncIOMotorClient(mongo_url)
db = client[os.environ['DB_NAME']]

async def convert_date_to_datetime(collection_name, date_fields):
    """Convert date fields to datetime in a collection"""
    print(f"\n📅 Converting dates in {collection_name}...")
    
    collection = db[collection_name]
    documents = await collection.find({}).to_list(10000)
    
    updated = 0
    for doc in documents:
        updates = {}
        for field in date_fields:
            if field in doc and isinstance(doc[field], date) and not isinstance(doc[field], datetime):
                # Convert date to datetime (midnight)
                updates[field] = datetime.combine(doc[field], datetime.min.time())
        
        if updates:
            await collection.update_one(
                {"_id": doc["_id"]},
                {"$set": updates}
            )
            updated += 1
    
    print(f"✅ Updated {updated} documents in {collection_name}")

async def migrate_database():
    """Run all migrations"""
    print("🚀 Starting database migration...")
    
    # Collections and their date fields
    migrations = [
        ("children", ["date_of_birth"]),
        ("enrollments", ["start_date", "end_date", "created_at"]),
        ("attendance", ["date", "created_at"]),
        ("payments", ["created_at"]),
        ("skill_progress", ["assessment_date", "updated_at"]),
        ("child_badges", ["earned_date"]),
        ("coach_checkins", ["checkin_date"]),
        ("replacement_requests", ["request_date", "created_at"]),
        ("feedback", ["created_at", "approved_at"]),
        ("media_uploads", ["uploaded_at"]),
        ("users", ["created_at"]),
        ("classes", ["created_at"]),
        ("programs", ["created_at"]),
        ("locations", ["created_at"]),
    ]
    
    for collection, fields in migrations:
        await convert_date_to_datetime(collection, fields)
    
    print("\n✅ Migration completed successfully!")

if __name__ == "__main__":
    asyncio.run(migrate_database())
