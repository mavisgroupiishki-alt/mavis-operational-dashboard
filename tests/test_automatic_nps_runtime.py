import asyncio
from datetime import datetime
from unittest.mock import AsyncMock, patch

from app import main


AS_OF = datetime.fromisoformat("2026-09-21T09:00:00+03:00")


def _task():
    return {
        "ID": "42",
        "TITLE": "NPS task",
        "STATUS": "5",
        "CREATED_DATE": "2026-09-15T10:00:00+03:00",
        "CLOSED_DATE": "2026-09-25T10:00:00+03:00",
        "UF_AUTO_213716165780": "9",
        "UF_AUTO_394851584352": "Ирина Богомольцева",
    }


def test_refresh_requests_tasks_by_created_date_for_previous_week():
    main.automatic_nps_cache.clear()
    main.automatic_nps_cache_time.clear()
    main.automatic_nps_tasks.clear()

    async def run():
        with patch.object(main.client, "tasks_for_group", new=AsyncMock(return_value=[_task()])) as fetch, patch.object(main, "broadcast", new=AsyncMock()):
            refresh = main.schedule_automatic_nps_refresh(AS_OF)
            await refresh
            args = fetch.await_args.args
            assert args[0] == 114
            assert args[1].date().isoformat() == "2026-09-14"
            assert args[2].date().isoformat() == "2026-09-21"

    asyncio.run(run())
    cached = main.cached_automatic_nps(AS_OF)
    assert cached["date_basis"] == "created_date"
    assert cached["overall"] == {"value": 9.0, "count": 1}
    assert cached["experts"]["Ирина Богомольцева"]["tasks"][0]["task_url"].endswith("/42/")
