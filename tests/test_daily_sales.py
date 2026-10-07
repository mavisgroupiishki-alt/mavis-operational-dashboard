import asyncio

from app.daily_sales import build_daily_sales_report, call_direction, duration_seconds, statistic_direction, summarize_daily_sales


def test_call_direction_and_duration_do_not_guess_unknown_values():
    assert call_direction({"DIRECTION": 1}) == "incoming"
    assert call_direction({"DIRECTION": "2"}) == "outgoing"
    assert call_direction({"DIRECTION": "sideways"}) == "unknown"
    assert duration_seconds({"DURATION": 120}) == 120
    assert duration_seconds({"DURATION": 2, "DURATION_TYPE": "min"}) == 120
    assert duration_seconds({"DURATION": "not-a-number"}) is None


def test_telephony_statistics_use_their_own_documented_call_types():
    assert statistic_direction({"CALL_TYPE": 1}) == "outgoing"
    assert statistic_direction({"CALL_TYPE": "2"}) == "incoming"
    assert statistic_direction({"CALL_TYPE": 3}) == "incoming"
    assert statistic_direction({"CALL_TYPE": 5}) == "unknown"


def test_summary_keeps_unclassified_calls_out_of_directional_metrics():
    report = summarize_daily_sales(
        leads=[{"SOURCE_ID": "DIRECT", "ASSIGNED_BY_ID": "1"}],
        deals=[{
            "SOURCE_ID": "DIRECT", "ASSIGNED_BY_ID": "1", "STAGE_ID": "NEW",
            "UF_CRM_1756973967704": "new",
        }],
        activities=[
            {"RESPONSIBLE_ID": "1", "DIRECTION": 1, "DURATION": 125},
            {"RESPONSIBLE_ID": "1", "DIRECTION": 2, "DURATION": 60},
            {"RESPONSIBLE_ID": "1", "DIRECTION": 9, "DURATION": 999},
            {"RESPONSIBLE_ID": "1", "DIRECTION": 1},
        ],
        meta={
            "sources": {"DIRECT": "Входящий звонок (прямой)"},
            "users": {"1": "Ирина"},
            "status_by_entity": {"DEAL_STAGE": {"NEW": "1. Новая сделка"}},
            "enums": {"UF_CRM_1756973967704": {"new": "Новый клиент"}},
        },
    )
    row = report["calls"]["by_manager"][0]
    assert (row["incoming_count"], row["outgoing_count"], row["unclassified_count"]) == (2, 1, 1)
    assert row["incoming_minutes"] == 2.1
    assert row["outgoing_minutes"] == 1.0
    assert row["without_duration_count"] == 1
    assert report["calls"]["unclassified_count"] == 1


class FakeBitrix:
    async def lead_list(self, filters, select):
        assert filters[">=DATE_CREATE"].startswith("2026-09-30")
        return [{"ID": "1", "SOURCE_ID": "DIRECT", "ASSIGNED_BY_ID": "7"}]

    async def deal_list(self, filters, select):
        if filters["CATEGORY_ID"] == 0:
            return [{"ID": "2", "SOURCE_ID": "DIRECT", "STAGE_ID": "NEW", "ASSIGNED_BY_ID": "7"}]
        assert filters["CATEGORY_ID"] == 20
        return [{"ID": "20", "CATEGORY_ID": 20, "STAGE_ID": "NEW", "ASSIGNED_BY_ID": "7"}]

    async def list_all(self, method, params):
        assert method == "voximplant.statistic.get"
        assert params["FILTER"][">=CALL_START_DATE"].startswith("2026-09-30")
        return [{"ID": "3", "PORTAL_USER_ID": "7", "CALL_TYPE": 1, "CALL_DURATION": 180}]

    async def meta(self):
        return {
            "sources": {"DIRECT": "Входящий звонок (прямой)"}, "users": {"7": "Ирина"},
            "status_by_entity": {"DEAL_STAGE": {"NEW": "1. Новая сделка"}}, "enums": {},
        }


def test_daily_report_uses_one_bitrix_calendar_day():
    report = asyncio.run(build_daily_sales_report(FakeBitrix(), "2026-09-30", "Europe/Minsk"))
    assert report["date"] == "2026-09-30"
    assert report["source"] == "Bitrix24 CRM (read-only)"
    assert report["leads"]["total"] == report["calls"]["total"] == 1
    assert report["deals"]["total"] == 2
    assert report["availability"] == {
        "leads": {"status": "online"}, "deals": {"status": "online"}, "calls": {"status": "online"},
    }
    assert report["calls"]["by_manager"] == [{
        "name": "Ирина", "incoming_count": 0, "outgoing_count": 1,
        "incoming_minutes": 0.0, "outgoing_minutes": 3.0,
        "unclassified_count": 0, "without_duration_count": 0,
    }]
