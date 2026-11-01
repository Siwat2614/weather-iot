"""
Weather & Air Quality Dashboard API
-----------------------------------
FastAPI backend for the weather-station dashboard.

Endpoints:
  GET /api/stations
  GET /api/stations/{station_id}/months
  GET /api/stations/{station_id}/latest
  GET /api/stations/{station_id}/history
  GET /

The dashboard supports historical data by month. Month boundaries are
interpreted in Asia/Bangkok and converted to UTC for MongoDB queries.
"""

import os
import logging
from datetime import datetime, timezone
from typing import Optional
from zoneinfo import ZoneInfo

from fastapi import FastAPI, HTTPException, Query
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pymongo import MongoClient, DESCENDING
from pymongo.errors import PyMongoError

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
MONGO_URL = os.getenv("MONGO_URL", "mongodb://mongodb:27017")
MONGO_DB_NAME = os.getenv("MONGO_DB_NAME", "weather_db")
MONGO_COLLECTION = os.getenv("MONGO_COLLECTION", "weather_readings")
ONLINE_THRESHOLD_SECONDS = int(os.getenv("ONLINE_THRESHOLD_SECONDS", "30"))

# Thailand timezone
LOCAL_TZ = ZoneInfo("Asia/Bangkok")

# Maximum records returned for a full calendar month.
MAX_HISTORY_LIMIT = 10000

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [webapp] %(levelname)s: %(message)s",
)

log = logging.getLogger("webapp")

app = FastAPI(
    title="IoT Weather & Air Quality Monitoring API"
)

client: Optional[MongoClient] = None
collection = None


# ---------------------------------------------------------------------------
# MongoDB
# ---------------------------------------------------------------------------
def get_collection():
    """Lazily connect/reconnect to MongoDB."""
    global client, collection

    if collection is not None:
        return collection

    try:
        client = MongoClient(
            MONGO_URL,
            serverSelectionTimeoutMS=5000
        )

        client.admin.command("ping")

        collection = client[
            MONGO_DB_NAME
        ][MONGO_COLLECTION]

        collection.create_index(
            [
                ("station_id", 1),
                ("received_at", -1)
            ]
        )

        log.info(
            "Connected to MongoDB at %s "
            "(db=%s, collection=%s)",
            MONGO_URL,
            MONGO_DB_NAME,
            MONGO_COLLECTION,
        )

        return collection

    except PyMongoError as e:
        log.error(
            "MongoDB connection error: %s",
            e
        )

        collection = None
        return None


# ---------------------------------------------------------------------------
# Serialization
# ---------------------------------------------------------------------------
def serialize(doc: dict) -> dict:
    """Convert MongoDB document into JSON-safe data."""

    doc = dict(doc)

    doc["_id"] = str(doc["_id"])

    if isinstance(
        doc.get("received_at"),
        datetime
    ):
        dt = doc["received_at"]

        if dt.tzinfo is None:
            dt = dt.replace(
                tzinfo=timezone.utc
            )

        doc["received_at"] = (
            dt.astimezone(
                timezone.utc
            ).isoformat()
        )

    return doc


# ---------------------------------------------------------------------------
# Month helper
# ---------------------------------------------------------------------------
def month_range_utc(month: str):
    """
    Convert YYYY-MM in Thailand local time
    into UTC datetime boundaries.
    """

    try:
        year, month_number = (
            int(value)
            for value in month.split("-")
        )

        if not 1 <= month_number <= 12:
            raise ValueError

        start_local = datetime(
            year,
            month_number,
            1,
            tzinfo=LOCAL_TZ,
        )

        if month_number == 12:
            end_local = datetime(
                year + 1,
                1,
                1,
                tzinfo=LOCAL_TZ,
            )
        else:
            end_local = datetime(
                year,
                month_number + 1,
                1,
                tzinfo=LOCAL_TZ,
            )

        return (
            start_local.astimezone(
                timezone.utc
            ),
            end_local.astimezone(
                timezone.utc
            ),
        )

    except (
        ValueError,
        TypeError
    ):
        raise HTTPException(
            status_code=400,
            detail="month must use YYYY-MM format",
        )


def build_query(
    station_id: str,
    month: Optional[str] = None
):
    query = {
        "station_id": station_id
    }

    if month:
        start, end = month_range_utc(month)

        query["received_at"] = {
            "$gte": start,
            "$lt": end,
        }

    return query


# ---------------------------------------------------------------------------
# Request logging
# ---------------------------------------------------------------------------
@app.middleware("http")
async def log_requests(
    request,
    call_next
):
    response = await call_next(request)

    log.info(
        "%s %s -> %s",
        request.method,
        request.url.path,
        response.status_code,
    )

    return response


# ---------------------------------------------------------------------------
# Stations
# ---------------------------------------------------------------------------
@app.get("/api/stations")
def list_stations():
    """Return all known station IDs."""

    col = get_collection()

    if col is None:
        raise HTTPException(
            status_code=500,
            detail="Database unavailable"
        )

    try:
        stations = col.distinct(
            "station_id"
        )

        return sorted(stations)

    except PyMongoError as e:
        log.error(
            "Database error in list_stations: %s",
            e
        )

        raise HTTPException(
            status_code=500,
            detail="Database error"
        )


# ---------------------------------------------------------------------------
# Months
# ---------------------------------------------------------------------------
@app.get(
    "/api/stations/{station_id}/months"
)
def list_months(
    station_id: str
):
    """
    Return every YYYY-MM month that actually
    exists in MongoDB.

    Uses Thailand timezone.
    """

    col = get_collection()

    if col is None:
        raise HTTPException(
            status_code=500,
            detail="Database unavailable"
        )

    try:
        pipeline = [
            {
                "$match": {
                    "station_id": station_id
                }
            },
            {
                "$group": {
                    "_id": {
                        "$dateToString": {
                            "format": "%Y-%m",
                            "date": "$received_at",
                            "timezone": "Asia/Bangkok",
                        }
                    }
                }
            },
            {
                "$sort": {
                    "_id": 1
                }
            },
            {
                "$project": {
                    "_id": 0,
                    "month": "$_id"
                }
            }
        ]

        rows = list(
            col.aggregate(pipeline)
        )

        return [
            row["month"]
            for row in rows
        ]

    except PyMongoError as e:
        log.error(
            "Database error in list_months: %s",
            e
        )

        raise HTTPException(
            status_code=500,
            detail="Database error"
        )


# ---------------------------------------------------------------------------
# Latest
# ---------------------------------------------------------------------------
@app.get(
    "/api/stations/{station_id}/latest"
)
def get_latest(
    station_id: str,
    month: Optional[str] = Query(
        default=None,
        pattern=r"^\d{4}-(0[1-9]|1[0-2])$",
    ),
):
    """
    Return latest reading.

    If month is provided, return the latest
    reading INSIDE that selected month.
    """

    col = get_collection()

    if col is None:
        raise HTTPException(
            status_code=500,
            detail="Database unavailable"
        )

    query = build_query(
        station_id,
        month
    )

    try:
        doc = col.find_one(
            query,
            sort=[
                (
                    "received_at",
                    DESCENDING
                )
            ],
        )

    except PyMongoError as e:
        log.error(
            "Database error in get_latest: %s",
            e
        )

        raise HTTPException(
            status_code=500,
            detail="Database error"
        )

    if doc is None:
        raise HTTPException(
            status_code=404,
            detail=(
                f"No data found for "
                f"station '{station_id}'"
            )
        )

    result = serialize(doc)

    # Selected month = historical data.
    if month:

        result["status"] = "HISTORICAL"

    else:

        try:
            received_dt = datetime.fromisoformat(
                result["received_at"]
            )

            now = datetime.now(
                timezone.utc
            )

            age = (
                now
                - received_dt.astimezone(
                    timezone.utc
                )
            ).total_seconds()

            result["status"] = (
                "ONLINE"
                if 0 <= age <= ONLINE_THRESHOLD_SECONDS
                else "OFFLINE"
            )

        except Exception:

            result["status"] = "UNKNOWN"

    return result


# ---------------------------------------------------------------------------
# History
# ---------------------------------------------------------------------------
@app.get(
    "/api/stations/{station_id}/history"
)
def get_history(
    station_id: str,

    limit: int = Query(
        default=100,
        ge=1,
        le=MAX_HISTORY_LIMIT,
    ),

    month: Optional[str] = Query(
        default=None,
        pattern=r"^\d{4}-(0[1-9]|1[0-2])$",
    ),
):
    """
    Return historical readings.

    When month=YYYY-MM is provided,
    only that Thailand calendar month is returned.
    """

    col = get_collection()

    if col is None:
        raise HTTPException(
            status_code=500,
            detail="Database unavailable"
        )

    query = build_query(
        station_id,
        month
    )

    try:

        cursor = (
            col.find(query)
            .sort(
                "received_at",
                DESCENDING
            )
            .limit(limit)
        )

        docs = [
            serialize(d)
            for d in cursor
        ]

    except PyMongoError as e:

        log.error(
            "Database error in get_history: %s",
            e
        )

        raise HTTPException(
            status_code=500,
            detail="Database error"
        )

    # Chart.js needs chronological order.
    docs.reverse()

    return docs


# ---------------------------------------------------------------------------
# Dashboard
# ---------------------------------------------------------------------------
app.mount(
    "/static",
    StaticFiles(directory="static"),
    name="static",
)


@app.get("/")
def dashboard():

    return FileResponse(
        "static/index.html"
    )
