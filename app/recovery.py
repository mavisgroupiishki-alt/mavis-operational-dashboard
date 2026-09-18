"""One-time recovery for the production plan saved before the 11 September redeploy."""

RECOVERY_MONTH = "2026-09"
RECOVERY_SCOPE = "production"
RECOVERY_CONTEXT_TYPE = "overall"
RECOVERY_CONTEXT_KEY = ""
RECOVERED_VALUES = {
    "closed_count": 145.0,
    "closed_amount": 160000.0,
    "avg_check": 1080.0,
    "new_count": 148.0,
    "new_amount": 160000.0,
    "period_closed_count": 44.0,
    "period_closed_amount": 47520.0,
    "new_to_success_pct": 30.0,
    "capacity_count": 237.0,
    "capacity_amount": 237166.0,
    "returns_count": 8.0,
    "returns_amount": 10815.0,
    "avg_production_days": 0.0,
    "avg_deviation_days": 0.0,
    "within_norm_pct": 0.0,
    "nps_avg": 9.5,
    "dormant_count": 0.0,
    "returned_to_production": 0.0,
    "dormant_with_reason_pct": 0.0,
}

# The original 1 September dormant-deal list was not retained. These are the
# figures confirmed by the operations team and are kept separately from live
# Bitrix history, which can be incomplete for old cross-funnel transitions.
SEPTEMBER_2026_DORMANT_BASELINE = {
    "baseline_date": "2026-09-01",
    "count": 320,
    "ids": [],
    "source": "confirmed_manual",
    "confirmed_to_return_count": 3,
    "confirmed_to_production_count": 7,
    "confirmed_revision": 2,
}


def restore_missing_production_plan(storage):
    """Restore the captured plan only when its exact context is absent.

    This never overwrites a plan entered in the dashboard.
    """
    context = f"{RECOVERY_SCOPE}|{RECOVERY_CONTEXT_TYPE}|{RECOVERY_CONTEXT_KEY}"
    if context in storage.plan_dict(RECOVERY_MONTH):
        return False
    storage.set_plans(
        RECOVERY_MONTH,
        RECOVERY_SCOPE,
        RECOVERY_CONTEXT_TYPE,
        RECOVERY_CONTEXT_KEY,
        RECOVERED_VALUES,
    )
    return True


def restore_confirmed_september_dormant_baseline(storage):
    """Apply the corrected, user-confirmed September baseline once."""
    current = storage.dormant_baseline(RECOVERY_MONTH)
    if current.get("confirmed_revision") == SEPTEMBER_2026_DORMANT_BASELINE["confirmed_revision"]:
        return False
    storage.set_dormant_baseline(RECOVERY_MONTH, SEPTEMBER_2026_DORMANT_BASELINE)
    return True
