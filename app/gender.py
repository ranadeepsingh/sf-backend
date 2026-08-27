"""Gender values used to guide generated contact avatars."""

from enum import Enum


class Gender(str, Enum):
    MALE = "male"
    FEMALE = "female"
    UNKNOWN = "unknown"


GENDER_VALUES = tuple(gender.value for gender in Gender)
