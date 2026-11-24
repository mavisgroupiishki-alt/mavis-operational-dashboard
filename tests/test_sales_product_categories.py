import unittest

from app.metrics import product_category, sales_product_categories


class SalesProductCategoriesTests(unittest.TestCase):
    def test_known_product_uses_business_category(self):
        self.assertEqual(product_category("Свидетельство СПК"), "Строительство")

    def test_uncommon_product_stays_visible_by_its_bitrix_title(self):
        self.assertEqual(product_category("Разработка документов по ОТ"), "Разработка документов по ОТ")
        self.assertNotEqual(product_category("Разработка документов по ОТ"), "Не определено")

    def test_category_order_keeps_uncommon_product_instead_of_unknown_bucket(self):
        categories = sales_product_categories([
            {"products": [
                {"category": "Разработка документов по ОТ"},
                {"category": "Строительство"},
                {"category": "Системы менеджмента"},
            ]},
        ])
        self.assertEqual(categories, [
            "Системы менеджмента",
            "Строительство",
            "Разработка документов по ОТ",
        ])


if __name__ == "__main__":
    unittest.main()
