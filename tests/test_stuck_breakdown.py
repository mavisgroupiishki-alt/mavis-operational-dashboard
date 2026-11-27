import unittest
from unittest.mock import patch
from app import main
from app.metrics import dormant_group, dormant_source_stage, split_dormant_completions, potential_return_field

class StuckBreakdownTests(unittest.TestCase):
    def test_groups(self):
        for stage in ('В работе', 'Отложенный спрос'):
            self.assertEqual(dormant_group(stage), 'active')
        for stage in ('Потенциальный возврат','Согласованный возврат','В счёт будущих услуг','Чёрный список','Сгоревшие'):
            self.assertEqual(dormant_group(stage), 'inactive')
        self.assertEqual(dormant_group('Возврат'), 'unknown')
        self.assertEqual([r['stage'] for r in split_dormant_completions([{'stage':'Согласованный возврат'},{'stage':'Возврат'}])[1]], ['Возврат'])
    def test_previous_stage(self):
        history = {'OWNER_ID': '1','ID': '3','CREATED_TIME':'2026-11-20','STAGE_ID':'C30:APOLOGY'}
        events = [{'OWNER_ID':'1','ID':'2','CREATED_TIME':'2026-11-19','STAGE_ID':'C30:PREP'}]
        self.assertEqual(dormant_source_stage(history, events, {'C30:PREP':'Согласованный возврат'}), 'Согласованный возврат')
        self.assertIsNone(dormant_source_stage(history, [], {}))
    def test_summary(self):
        current = [{'id':'1','stage':'В работе','amount':100,'company_id':'5','stuck_reasons':['НЕТ ЛЮДЕЙ']}, {'id':'2','stage':'Потенциальный возврат','amount':200,'company_id':'5','potential_return_comment':'Комментарий'}]
        transitions=[{'id':'3','source_stage':'В работе'},{'id':'4','source_stage':None}]
        details={'production':{'dormant':current,'dormant_to_production':transitions,'dormant_to_return':[{'id':'5','source_stage':'Согласованный возврат'}]}}
        with patch.object(main.storage,'dormant_baseline',return_value={}):
            data=main._stuck_breakdown('2026-11',details,{})
        self.assertEqual(data['all']['count'],2)
        self.assertEqual(data['all']['companies'],1)
        self.assertEqual(data['active']['reasons'][0]['name'],'Нет людей')
        self.assertEqual(data['inactive']['to_return']['count'],1)
        self.assertEqual(data['unknown']['to_production']['count'],1)
        self.assertEqual(data['potential'][0]['potential_return_comment'],'Комментарий')
    def test_comment_field(self):
        self.assertEqual(potential_return_field({'deal_fields':{'UF_TEST':{'formLabel':'Комментарий к потенциальному возврату'}}}), 'UF_TEST')
