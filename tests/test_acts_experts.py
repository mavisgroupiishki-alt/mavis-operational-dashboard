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


def test_report_excludes_a_task_when_the_linked_deal_closed_in_another_month():
    report = build_acts_experts_report(
        tasks=[
            {
                "ID": "1", "TITLE": "Акт в сентябре", "CREATED_DATE": "2026-09-02T10:00:00+03:00",
                "CREATED_BY": "10", "STAGE_ID": "1480", "UF_CRM_TASK_DEAL": ["D_900"],
                "ACTS_DEAL_CLOSEDATE": "2026-09-15T18:00:00+03:00",
            },
            {
                "ID": "2", "TITLE": "Акт создан в сентябре, сделка в августе", "CREATED_DATE": "2026-09-03T10:00:00+03:00",
                "CREATED_BY": "10", "STAGE_ID": "1480", "UF_CRM_TASK": "D_901",
                "ACTS_DEAL_CLOSEDATE": "2026-08-31T18:00:00+03:00",
            },
        ],
        users={"10": "Елизавета Горбатова"},
        stages=[{"id": "1480", "title": "СКАН ЕСТЬ"}],
        month="2026-09",
        portal="https://mavisgroup.bitrix24.by",
    )

    lisa = next(expert for expert in report["experts"] if expert["name"] == "Елизавета Горбатова")
    assert (lisa["total"], lisa["scan"], lisa["crm_mismatch_count"]) == (1, 1, 1)
    assert lisa["crm_mismatch"][0]["deal_id"] == "901"
    assert lisa["crm_mismatch"][0]["deal_close_date"].startswith("2026-08-31")
