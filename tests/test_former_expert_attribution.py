import unittest

from app.metrics import production_expert_id


class FormerExpertAttributionTests(unittest.TestCase):
    def test_closed_product_uses_current_responsible_person(self):
        deal = {"ASSIGNED_BY_ID": "responsible-expert", "MOVED_BY_ID": "tatiana-closer"}

        self.assertEqual(production_expert_id(deal, closed_success=True), "responsible-expert")

    def test_open_product_keeps_current_responsible_person(self):
        deal = {"ASSIGNED_BY_ID": "active-owner", "MOVED_BY_ID": "iolanta"}

        self.assertEqual(production_expert_id(deal, closed_success=False), "active-owner")

    def test_closed_product_falls_back_when_bitrix_has_no_mover(self):
        deal = {"ASSIGNED_BY_ID": "iolanta"}

        self.assertEqual(production_expert_id(deal, closed_success=True), "iolanta")


if __name__ == "__main__":
    unittest.main()
