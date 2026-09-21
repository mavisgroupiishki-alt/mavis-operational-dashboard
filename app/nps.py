from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo


NPS_GROUP_ID = 114
NPS_SCORE_FIELD = "UF_AUTO_213716165780"
NPS_EXPERT_FIELD = "UF_AUTO_394851584352"
NPS_COMPLETED_STATUS = "5"


def _as_local(value, timezone_name):
    if not value:
        return None
    if isinstance(value, datetime):
        point = value
    else:
        text = str(value).replace("Z", "+00:00")
        try:
            point = datetime.fromisoformat(text)
        except ValueError:
            return None
    zone = ZoneInfo(timezone_name)
    if point.tzinfo is None:
        return point.replace(tzinfo=zone)
    return point.astimezone(zone)


def previous_calendar_week(as_of=None, timezone_name="Europe/Minsk"):
    zone = ZoneInfo(timezone_name)
    now = _as_local(as_of, timezone_name) if as_of else datetime.now(zone)
    current_monday = datetime.combine(now.date() - timedelta(days=now.weekday()), time.min, tzinfo=zone)
    return current_monday - timedelta(days=7), current_monday


def _score(value):
    if isinstance(value, list):
        value = value[0] if value else None
    try:
        score = float(str(value).replace(",", "."))
    except (TypeError, ValueError):
        return None
    if score < 0 or score > 10:
        return None
    return score


def _expert(value):
    if isinstance(value, list):
        value = value[0] if value else None
    return str(value).strip() if value else None


def _deal_id(task):
    for field in ("UF_CRM_TASK_DEAL", "UF_CRM_TASK"):
        value = task.get(field)
        if isinstance(value, list):
            value = value[0] if value else None
        if value:
            return str(value).replace("D_", "")
    return None


def aggregate_automatic_nps(tasks, as_of=None, timezone_name="Europe/Minsk"):
    week_start, week_end = previous_calendar_week(as_of, timezone_name)
    grouped = {}
    excluded_without_score = 0
    unmatched_expert_count = 0

    for task in tasks:
        if str(task.get("STATUS")) != NPS_COMPLETED_STATUS:
            continue
        created_at = _as_local(task.get("CREATED_DATE"), timezone_name)
        if not created_at or not week_start <= created_at < week_end:
            continue

        score = _score(task.get(NPS_SCORE_FIELD))
        if score is None:
            excluded_without_score += 1
            continue
        expert = _expert(task.get(NPS_EXPERT_FIELD))
        if not expert:
            unmatched_expert_count += 1
            continue

        grouped.setdefault(expert, []).append({
            "id": str(task.get("ID")),
            "title": task.get("TITLE") or "Задача NPS",
            "score": score,
            "created_date": created_at.date().isoformat(),
            "closed_date": (_as_local(task.get("CLOSED_DATE"), timezone_name) or created_at).date().isoformat(),
            "deal_id": _deal_id(task),
        })

    experts = {}
    all_scores = []
    for expert, rows in grouped.items():
        scores = [row["score"] for row in rows]
        all_scores.extend(scores)
        experts[expert] = {
            "value": round(sum(scores) / len(scores), 1),
            "count": len(scores),
            "tasks": rows,
        }

    return {
        "status": "online",
        "date_basis": "created_date",
        "week_start": week_start.date().isoformat(),
        "week_end": (week_end - timedelta(days=1)).date().isoformat(),
        "overall": {
            "value": round(sum(all_scores) / len(all_scores), 1) if all_scores else None,
            "count": len(all_scores),
        },
        "experts": experts,
        "excluded_without_score": excluded_without_score,
        "unmatched_expert_count": unmatched_expert_count,
    }
