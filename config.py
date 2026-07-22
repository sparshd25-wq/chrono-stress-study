"""Application-wide study configuration."""

import os
from pathlib import Path


APP_NAME = "ChronoStress Study"
STUDY_DURATION_DAYS = 21
DAILY_ASSESSMENT_TARGET = 3
BASE_DIR = Path(__file__).resolve().parent
DATABASE_PATH = BASE_DIR / "study_data.db"
DATA_DIR = BASE_DIR / "data"
EXPORTS_DIR = BASE_DIR / "exports"
LOGS_DIR = BASE_DIR / "logs"
ASSESSMENT_VERSION = "1.0.0"
ADMIN_USERNAME = os.getenv("CHRONOSTRESS_ADMIN_USERNAME", "admin")
ADMIN_ACCESS_CODE = os.getenv("CHRONOSTRESS_ADMIN_ACCESS_CODE", "ChronoStressAdmin2026")

LOCATION_OPTIONS = (
    "Home",
    "Hostel",
    "University",
    "Library",
    "Travelling",
    "Other",
)
ACTIVITY_OPTIONS = (
    "Studying",
    "Working",
    "Walking",
    "Eating",
    "Socialising",
    "Resting",
    "Exercise",
    "Driving",
    "Other",
)
WORKLOAD_OPTIONS = ("Very Low", "Low", "Moderate", "High", "Very High")
EVENT_TYPES = (
    "Academic",
    "Work",
    "Relationship",
    "Family",
    "Health",
    "Financial",
    "Travel",
    "Other",
)
EVENT_DURATIONS = (
    "Less than 5 min",
    "5-30 min",
    "30-60 min",
    "1-3 hours",
    "More than 3 hours",
)
