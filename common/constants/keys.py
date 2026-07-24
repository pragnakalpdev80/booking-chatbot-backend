from enum import Enum


class CacheKey(Enum):
    USER_PROFILE = "user_profile_{user_id}"


class CacheTTL:
    HOUR = 3600
