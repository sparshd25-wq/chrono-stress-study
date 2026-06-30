"""Application-wide study configuration."""

from pathlib import Path


APP_NAME = "ChronoStress Study"
STUDY_DURATION_DAYS = 21
DAILY_ASSESSMENT_TARGET = 3
BASE_DIR = Path(__file__).resolve().parent
DATABASE_PATH = BASE_DIR / "study_data.db"

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

