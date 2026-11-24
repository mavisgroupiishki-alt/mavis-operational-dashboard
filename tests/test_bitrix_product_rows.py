import unittest
from unittest.mock import AsyncMock

from app.bitrix import BitrixClient


class BitrixProductRowsTests(unittest.IsolatedAsyncioTestCase):
    async def test_product_id_is_hydrated_with_catalog_title(self):
        client = BitrixClient("https://example.bitrix24.by/rest/1/token/")

        async def call(method, params):
            commands = params["cmd"]
            if any(key.startswith("d") for key in commands):
                return {"result": {"result": {"d0": [{"PRODUCT_ID": "58"}]}, "result_error": {}}}
            return {"result": {"result": {"p0": {"ID": "58", "NAME": "Лицензия МЧС"}}, "result_error": {}}}

        client.call = AsyncMock(side_effect=call)
        rows = await client.product_rows_many([{"ID": "10"}])
        await client.close()

        self.assertEqual(rows["10"], [{"PRODUCT_ID": "58", "PRODUCT_NAME": "Лицензия МЧС"}])


if __name__ == "__main__":
    unittest.main()
