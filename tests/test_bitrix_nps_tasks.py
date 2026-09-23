import asyncio
import unittest
from datetime import datetime
from unittest.mock import AsyncMock

from app.bitrix import BitrixClient


class BitrixNpsTaskFetchTests(unittest.TestCase):
    def test_fetches_project_tasks_without_server_side_status_or_date_filters(self):
        async def check():
            client = BitrixClient("https://example.bitrix24.by/rest/1/token")
            client.list_all = AsyncMock(return_value=[])
            try:
                await client.tasks_for_group(
                    114,
                    datetime.fromisoformat("2026-09-14T00:00:00+03:00"),
                    datetime.fromisoformat("2026-09-21T00:00:00+03:00"),
                )
            finally:
                await client.close()

            params = client.list_all.await_args.args[1]
            self.assertEqual(params["filter"], {"GROUP_ID": 114})
            self.assertIn("GROUP_ID", params["select"])

        asyncio.run(check())


if __name__ == "__main__":
    unittest.main()
