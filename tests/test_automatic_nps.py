from datetime import datetime

from app.nps import aggregate_automatic_nps, previous_calendar_week


AS_OF = datetime.fromisoformat("2026-09-21T09:00:00+03:00")


def task(identifier, created, closed, score, expert="Ирина Богомольцева", status="5"):
    return {
        "ID": str(identifier),
        "TITLE": f"NPS {identifier}",
        "STATUS": status,
        "CREATED_DATE": created,
        "CLOSED_DATE": closed,
        "UF_AUTO_213716165780": score,
        "UF_AUTO_394851584352": expert,
    }


def test_previous_calendar_week_is_monday_to_sunday():
    start, end = previous_calendar_week(AS_OF)
    assert start.isoformat().startswith("2026-09-14T00:00:00")
    assert end.isoformat().startswith("2026-09-21T00:00:00")


def test_automatic_nps_uses_task_created_date_not_closed_date():
    result = aggregate_automatic_nps([
        task(1, "2026-09-15T10:00:00+03:00", "2026-09-22T11:00:00+03:00", 10),
        task(2, "2026-09-18T10:00:00+03:00", "2026-09-18T11:00:00+03:00", 8),
        task(3, "2026-09-13T10:00:00+03:00", "2026-09-18T11:00:00+03:00", 1),
        task(4, "2026-09-19T10:00:00+03:00", "2026-09-19T11:00:00+03:00", None),
    ], AS_OF)

    assert result["date_basis"] == "created_date"
    assert result["week_start"] == "2026-09-14"
    assert result["week_end"] == "2026-09-20"
    assert result["overall"] == {"value": 9.0, "count": 2}
    assert result["experts"]["Ирина Богомольцева"]["count"] == 2
    assert result["excluded_without_score"] == 1
    assert result["fetched_task_count"] == 4
    assert result["completed_task_count"] == 4
    assert result["created_in_week_count"] == 3


def test_automatic_nps_ignores_open_tasks_even_when_created_in_week():
    result = aggregate_automatic_nps([
        task(1, "2026-09-15T10:00:00+03:00", None, 10, status="2"),
    ], AS_OF)

    assert result["overall"] == {"value": None, "count": 0}
    assert result["excluded_without_score"] == 0
