import unittest

from app.metrics import filter_sales_details


class SalesOperationalBreakdownTests(unittest.TestCase):
    def test_active_deals_drilldown_uses_current_funnel_and_manager_filter(self):
        details = {
            "active": [
                {"id": "101", "title": "Активная сделка Ирины", "manager": "Ирина", "stage": "КП отправлено"},
                {"id": "102", "title": "Активная сделка Романа", "manager": "Роман", "stage": "Переговоры"},
            ],
            "leads": [],
            "deals": [],
        }

        rows = filter_sales_details(details, "active_deals", manager="Ирина")

        self.assertEqual([row["id"] for row in rows], ["101"])

    def test_stage_drilldown_uses_active_deals_only(self):
        details = {
            "active": [
                {"id": "101", "stage": "КП отправлено"},
                {"id": "102", "stage": "Переговоры"},
            ],
            "leads": [],
            "deals": [{"id": "103", "stage": "КП отправлено", "period_type": "current"}],
        }

        rows = filter_sales_details(details, "deals", stage="КП отправлено")

        self.assertEqual([row["id"] for row in rows], ["101"])


if __name__ == "__main__":
    unittest.main()
