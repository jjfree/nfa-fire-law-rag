"""Persist local Streamlit preferences in the configured database."""

from app.db import session_scope
from app.models import UiPreference

DEFAULT_DISPLAY_RESULT_COUNT = 8
MIN_DISPLAY_RESULT_COUNT = 1
MAX_DISPLAY_RESULT_COUNT = 20
_DISPLAY_RESULT_COUNT_KEY = "display_result_count"


def get_display_result_count() -> int:
    with session_scope() as db:
        preference = db.get(UiPreference, _DISPLAY_RESULT_COUNT_KEY)
        if preference is None:
            return DEFAULT_DISPLAY_RESULT_COUNT
        count = preference.int_value
        if MIN_DISPLAY_RESULT_COUNT <= count <= MAX_DISPLAY_RESULT_COUNT:
            return count
        return DEFAULT_DISPLAY_RESULT_COUNT


def save_display_result_count(count: int) -> None:
    if isinstance(count, bool) or not isinstance(count, int):
        raise TypeError("顯示結果數必須是整數")
    if not MIN_DISPLAY_RESULT_COUNT <= count <= MAX_DISPLAY_RESULT_COUNT:
        raise ValueError("顯示結果數必須介於 1 至 20")
    with session_scope() as db:
        preference = db.get(UiPreference, _DISPLAY_RESULT_COUNT_KEY)
        if preference is None:
            db.add(UiPreference(key=_DISPLAY_RESULT_COUNT_KEY, int_value=count))
        else:
            preference.int_value = count
