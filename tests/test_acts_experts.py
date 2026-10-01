from app.acts_experts import build_acts_experts_report


def test_report_uses_current_month_task_creator_and_stage_name():
    report = build_acts_experts_report(
        tasks=[
            {"ID": "1", "TITLE": "Амис-техно", "CREATED_DATE": "2026-09-02T10:00:00+03:00", "CREATED_BY": "10", "STAGE_ID": "1480"},
            {"ID": "2", "TITLE": "Диптера", "CREATED_DATE": "2026-09-03T10:00:00+03:00", "CREATED_BY": "10", "STAGE_ID": "264"},
            {"ID": "3", "TITLE": "Без ответа", "CREATED_DATE": "2026-09-04T10:00:00+03:00", "CREATED_BY": "10", "STAGE_ID": "9"},
            {"ID": "4", "TITLE": "Август", "CREATED_DATE": "2026-08-30T10:00:00+03:00", "CREATED_BY": "10", "STAGE_ID": "9"},
            {"ID": "5", "TITLE": "Исторический акт", "CREATED_DATE": "2026-09-12T10:00:00+03:00", "CREATED_BY": "20", "STAGE_ID": "264"},
        ],
        users={"10": "Елизавета Горбатова", "20": "Иоланта Кананович"},
        stages=[{"id": "1480", "title": "СКАН ЕСТЬ"}, {"id": "264", "title": "Архив"}, {"id": "9", "title": "Звонок"}],
        month="2026-09",
        portal="https://mavisgroup.bitrix24.by",
    )
    lisa = next(expert for expert in report["experts"] if expert["name"] == "Елизавета Горбатова")
    assert (lisa["total"], lisa["scan"], lisa["archive"], lisa["no_confirmation"]) == (3, 1, 1, 1)
    assert lisa["pending"][0]["url"].endswith("/tasks/task/view/3/")
    assert lisa["scan_tasks"][0]["title"] == "Амис-техно"
    assert lisa["archive_tasks"][0]["title"] == "Диптера"
    iolanta = next(expert for expert in report["experts"] if expert["name"] == "Иоланта Кананович")
    assert (iolanta["total"], iolanta["scan"], iolanta["archive"], iolanta["no_confirmation"]) == (1, 0, 1, 0)
