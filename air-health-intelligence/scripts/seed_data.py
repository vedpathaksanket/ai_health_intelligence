"""
scripts/seed_data.py
Seed MongoDB with realistic demo air quality data for development/testing.
Run: python scripts/seed_data.py
"""
import asyncio
import random
from datetime import datetime, timedelta
from motor.motor_asyncio import AsyncIOMotorClient

MONGO_URI = "mongodb://localhost:27017"
DB_NAME   = "air_health_intelligence"

CITIES = {
    "Delhi":     (28.6139, 77.2090, 180, 60),   # (lat, lon, base_aqi, variance)
    "Mumbai":    (19.0760, 72.8777, 95,  30),
    "Bangalore": (12.9716, 77.5946, 75,  25),
    "Chennai":   (13.0827, 80.2707, 88,  28),
    "Kolkata":   (22.5726, 88.3639, 130, 40),
    "Hyderabad": (17.3850, 78.4867, 100, 35),
}

def _aqi_category(aqi):
    if aqi <= 50:  return "Good"
    if aqi <= 100: return "Moderate"
    if aqi <= 150: return "Unhealthy for Sensitive Groups"
    if aqi <= 200: return "Unhealthy"
    if aqi <= 300: return "Very Unhealthy"
    return "Hazardous"

def _make_reading(city, lat, lon, base_aqi, variance, timestamp):
    aqi = max(10, base_aqi + random.gauss(0, variance))
    pm25 = aqi * 0.45 + random.gauss(0, 5)
    pm10 = pm25 * 1.6 + random.gauss(0, 8)
    no2  = aqi * 0.3 + random.gauss(0, 10)
    o3   = max(0, 40 + random.gauss(0, 15))
    co   = max(0, 1.2 + random.gauss(0, 0.3))
    so2  = max(0, aqi * 0.05 + random.gauss(0, 2))

    return {
        "city": city,
        "country": "IN",
        "latitude": lat,
        "longitude": lon,
        "timestamp": timestamp,
        "aqi": round(aqi, 1),
        "aqi_category": _aqi_category(aqi),
        "pollutants": {
            "pm25": round(max(0, pm25), 1),
            "pm10": round(max(0, pm10), 1),
            "no2":  round(max(0, no2), 1),
            "o3":   round(o3, 1),
            "co":   round(co, 2),
            "so2":  round(max(0, so2), 1),
        },
        "weather": {
            "temperature": round(22 + random.gauss(0, 6), 1),
            "humidity":    round(max(10, min(100, 60 + random.gauss(0, 15))), 1),
            "wind_speed":  round(max(0, 3 + random.gauss(0, 1.5)), 1),
            "wind_direction": random.randint(0, 359),
            "pressure":    round(1013 + random.gauss(0, 5), 1),
            "visibility":  round(max(0.5, 8 + random.gauss(0, 3)), 1),
        },
        "source": "seeded",
    }


async def seed():
    client = AsyncIOMotorClient(MONGO_URI)
    db     = client[DB_NAME]
    col    = db["air_quality_readings"]

    now   = datetime.utcnow()
    docs  = []
    HOURS = 72          # 3 days of history
    INTERVAL_MINUTES = 15

    steps = (HOURS * 60) // INTERVAL_MINUTES
    print(f"Seeding {len(CITIES)} cities × {steps} time points = {len(CITIES)*steps} documents…")

    for city, (lat, lon, base_aqi, variance) in CITIES.items():
        for i in range(steps):
            ts = now - timedelta(minutes=i * INTERVAL_MINUTES)
            # Diurnal variation: worse at rush hours (7-10, 18-21)
            hour = ts.hour
            diurnal = 20 if (7 <= hour <= 10 or 18 <= hour <= 21) else 0
            docs.append(_make_reading(city, lat, lon, base_aqi + diurnal, variance, ts))

    # Insert in batches of 500
    batch = 500
    for i in range(0, len(docs), batch):
        await col.insert_many(docs[i:i+batch])
        print(f"  Inserted {min(i+batch, len(docs))}/{len(docs)}")

    # Create indexes
    from pymongo import ASCENDING, DESCENDING, IndexModel
    await col.create_indexes([
        IndexModel([("city", ASCENDING), ("timestamp", DESCENDING)]),
        IndexModel([("timestamp", DESCENDING)]),
    ])

    count = await col.count_documents({})
    print(f"\n✅ Seeding complete. Total documents: {count}")
    client.close()


if __name__ == "__main__":
    asyncio.run(seed())
