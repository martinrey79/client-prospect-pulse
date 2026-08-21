"""Canonical domain enums (§3.1)."""

from enum import Enum


class EntityType(str, Enum):
    CLIENT = "client"
    PROSPECT = "prospect"


class Importance(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class InfoType(str, Enum):
    WEB_SEARCH = "web_search"
    WEBSITE = "website"
    FILE = "file"
    SOCIAL_MEDIA = "social_media"
    MANUAL = "manual"
