"""UI settings survive separate database connections and app restarts."""

from contextlib import contextmanager

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app import ui_preferences
from app.db import Base
from app.models import UiPreference  # noqa: F401 - register the table


def test_display_result_count_survives_database_reopen(tmp_path, monkeypatch):
    database_url = f"sqlite:///{(tmp_path / 'preferences.db').as_posix()}"
    engine = create_engine(database_url)
    Base.metadata.create_all(engine)

    @contextmanager
    def use_engine():
        with Session(engine) as db:
            try:
                yield db
                db.commit()
            except Exception:
                db.rollback()
                raise

    monkeypatch.setattr(ui_preferences, "session_scope", use_engine)
    assert ui_preferences.get_display_result_count() == 8
    ui_preferences.save_display_result_count(13)
    engine.dispose()

    engine = create_engine(database_url)
    assert ui_preferences.get_display_result_count() == 13
    ui_preferences.save_display_result_count(4)
    assert ui_preferences.get_display_result_count() == 4
    engine.dispose()


@pytest.mark.parametrize("count", [0, 21, True, 8.5, "8"])
def test_display_result_count_rejects_invalid_values(count):
    expected_error = ValueError if isinstance(count, int) and not isinstance(count, bool) else TypeError
    with pytest.raises(expected_error):
        ui_preferences.save_display_result_count(count)
