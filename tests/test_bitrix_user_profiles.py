import unittest
from unittest.mock import AsyncMock

from app.bitrix import BitrixClient


class BitrixUserProfilesTests(unittest.IsolatedAsyncioTestCase):
    async def test_meta_keeps_active_and_dismissed_people_distinct(self):
        client = BitrixClient("https://example.test/rest/1/token")
        client.list_all = AsyncMock(side_effect=[
            [{"ID": "1", "NAME": "Работающий", "LAST_NAME": "Эксперт", "ACTIVE": "Y"}],
            [{"ID": "2", "NAME": "Иоланта", "LAST_NAME": "Кананович", "ACTIVE": "N"}],
            [],
        ])
        client.call = AsyncMock(side_effect=[{"result": {}}, {"result": {}}])

        try:
            meta = await client.meta()
        finally:
            await client.close()

        self.assertEqual(
            meta["user_options"],
            [
                {"id": "1", "name": "Работающий Эксперт", "active": True},
                {"id": "2", "name": "Иоланта Кананович", "active": False},
            ],
        )


if __name__ == "__main__":
    unittest.main()
