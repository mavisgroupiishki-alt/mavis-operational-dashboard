import json
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import quote

import httpx

DEFAULT_MANAGERS = ["Ирина Богомольцева", "Роман Авсеенко"]
# Актуальные исполнители, найденные в аудите воронки Производство.
# Состав можно менять в интерфейсе без правки кода.
DEFAULT_EXPERTS = ["Екатерина Николаева", "Елизавета Горбатова", "Ольга Панькова"]


class Storage:
    """Persistent settings storage.

    If SUPABASE_URL + SUPABASE_KEY are configured, Supabase KV is the source of truth.
    Otherwise SQLite is used as a local fallback (ephemeral on Render Free).
    """

    def __init__(self, path: Path, supabase_url: str = "", supabase_key: str = ""):
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.supabase_url = (supabase_url or "").rstrip("/")
        self.supabase_key = (supabase_key or "").strip()
        self.remote_enabled = bool(self.supabase_url and self.supabase_key)
        self.last_remote_error = ""
        self.mem = {}
        self._init_local()

    @property
    def backend_name(self) -> str:
        return "Supabase" if self.remote_enabled and not self.last_remote_error else ("Supabase (fallback SQLite)" if self.remote_enabled else "SQLite local")

    def connect(self):
        c = sqlite3.connect(self.path)
        c.row_factory = sqlite3.Row
        return c

    def _init_local(self):
        with self.connect() as c:
            c.execute("""
            CREATE TABLE IF NOT EXISTS kv_local(
              key TEXT PRIMARY KEY,
              value TEXT NOT NULL DEFAULT '{}',
              updated_at TEXT NOT NULL DEFAULT ''
            )""")
            c.commit()

    def _headers(self):
        return {
            "apikey": self.supabase_key,
            "Authorization": f"Bearer {self.supabase_key}",
            "Content-Type": "application/json",
        }

    def _remote_get(self, key: str):
        if not self.remote_enabled:
            return None
        url = f"{self.supabase_url}/rest/v1/mavis_dashboard_kv"
        try:
            with httpx.Client(timeout=8.0) as client:
                r = client.get(url, params={"select": "value", "key": f"eq.{key}", "limit": "1"}, headers=self._headers())
                r.raise_for_status()
                rows = r.json()
            self.last_remote_error = ""
            if rows:
                return rows[0].get("value")
            return None
        except Exception as e:
            self.last_remote_error = str(e)
            return None

    def _remote_set(self, key: str, value: Any) -> bool:
        if not self.remote_enabled:
            return False
        url = f"{self.supabase_url}/rest/v1/mavis_dashboard_kv"
        headers = self._headers()
        headers["Prefer"] = "resolution=merge-duplicates,return=minimal"
        payload = {
            "key": key,
            "value": value,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
        try:
            with httpx.Client(timeout=8.0) as client:
                r = client.post(url, params={"on_conflict": "key"}, headers=headers, json=payload)
                r.raise_for_status()
            self.last_remote_error = ""
            return True
        except Exception as e:
            self.last_remote_error = str(e)
            return False

    def _local_get(self, key: str, default=None):
        with self.connect() as c:
            row = c.execute("SELECT value FROM kv_local WHERE key=?", (key,)).fetchone()
        if not row:
            return default
        try:
            return json.loads(row["value"])
        except Exception:
            return default

    def _local_set(self, key: str, value: Any):
        ts = datetime.now(timezone.utc).isoformat()
        raw = json.dumps(value, ensure_ascii=False)
        with self.connect() as c:
            c.execute("""INSERT INTO kv_local(key,value,updated_at) VALUES(?,?,?)
            ON CONFLICT(key) DO UPDATE SET value=excluded.value,updated_at=excluded.updated_at""", (key, raw, ts))
            c.commit()

    def _legacy_get(self, key: str):
        """Read settings from the old Render persistent disk during Supabase migration.

        v2.2/v2.3 commonly stored the SQLite DB under /var/data. v2.4 can
        copy those values into Supabase automatically before the disk is removed.
        """
        candidates = [Path("/var/data/mavis_dashboard_v2.sqlite3"), Path("/var/data/mavis_dashboard.sqlite3")]
        for db in candidates:
            if not db.exists() or db.resolve() == self.path.resolve():
                continue
            try:
                c = sqlite3.connect(db)
                c.row_factory = sqlite3.Row
                row = c.execute("SELECT value FROM kv_local WHERE key=?", (key,)).fetchone()
                c.close()
                if row:
                    return json.loads(row["value"])
            except Exception:
                continue
        return None

    def _get(self, key: str, default):
        if key in self.mem:
            return self.mem[key]
        if self.remote_enabled:
            value = self._remote_get(key)
            if value is not None:
                self._local_set(key, value)  # warm fallback cache
                self.mem[key] = value
                return value
            # One-time automatic migration from current/legacy SQLite into Supabase.
            local_value = self._local_get(key, None)
            if local_value is None:
                local_value = self._legacy_get(key)
            if local_value is not None:
                if self._remote_set(key, local_value):
                    self._local_set(key, local_value)
                    self.mem[key] = local_value
                    return local_value
        value = self._local_get(key, default)
        self.mem[key] = value
        return value

    def _set(self, key: str, value: Any):
        # Always keep a local mirror; Supabase remains durable source when configured.
        self.mem[key] = value
        self._local_set(key, value)
        if self.remote_enabled:
            self._remote_set(key, value)

    # ---------- Plans ----------
    def plan_dict(self, month: str):
        value = self._get(f"plans:{month}", {})
        return value if isinstance(value, dict) else {}

    def get_plans(self, month, scope=None, context_type=None, context_key=None):
        out = []
        for ctx, values in self.plan_dict(month).items():
            parts = (ctx.split("|", 2) + ["", "", ""])[:3]
            s, ctype, ckey = parts
            if scope is not None and s != scope:
                continue
            if context_type is not None and ctype != context_type:
                continue
            if context_key is not None and ckey != context_key:
                continue
            for metric, value in (values or {}).items():
                out.append({"month": month, "scope": s, "context_type": ctype, "context_key": ckey, "metric": metric, "value": value})
        return out

    def set_plans(self, month, scope, context_type, context_key, values):
        all_plans = self.plan_dict(month)
        ctx = f"{scope}|{context_type}|{context_key or ''}"
        current = dict(all_plans.get(ctx) or {})
        for metric, value in values.items():
            try:
                current[metric] = float(value or 0)
            except Exception:
                continue
        all_plans[ctx] = current
        self._set(f"plans:{month}", all_plans)

    # ---------- Field mappings ----------
    def get_mappings(self):
        value = self._get("mappings", {})
        return value if isinstance(value, dict) else {}

    def set_mapping(self, name, field_code):
        value = self.get_mappings()
        value[name] = field_code or ""
        self._set("mappings", value)

    # ---------- Team ----------
    def team(self):
        default = {"managers": list(DEFAULT_MANAGERS), "experts": list(DEFAULT_EXPERTS)}
        value = self._get("team", default)
        if not isinstance(value, dict):
            value = default
        return {
            "managers": list(value.get("managers") or []),
            "experts": list(value.get("experts") or []),
        }

    def add_team_member(self, role, name):
        if role not in {"manager", "expert"}:
            raise ValueError("bad role")
        team = self.team()
        key = "managers" if role == "manager" else "experts"
        if name and name not in team[key]:
            team[key].append(name)
        self._set("team", team)

    def remove_team_member(self, role, name):
        team = self.team()
        key = "managers" if role == "manager" else "experts"
        team[key] = [x for x in team[key] if x != name]
        self._set("team", team)

    # ---------- Tile comments ----------
    def comments(self, month):
        value = self._get(f"comments:{month}", {})
        return value if isinstance(value, dict) else {}

    def set_comment(self, month, scope, metric, comment):
        value = self.comments(month)
        value[f"{scope}|{metric}"] = {
            "comment": comment or "",
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
        self._set(f"comments:{month}", value)

    # ---------- Manual NPS ----------
    def _nps_entries(self, month):
        key = f"nps_entries:{month}"
        value = self._get(key, None)
        if isinstance(value, list):
            return value

        # Migrate v2.4 single-value-per-expert structure without losing data.
        legacy = self._get(f"nps:{month}", {})
        entries = []
        if isinstance(legacy, dict):
            for expert, row in legacy.items():
                if not isinstance(row, dict):
                    continue
                try:
                    score = float(row.get("value"))
                except Exception:
                    continue
                entries.append({
                    "id": str(uuid.uuid4()),
                    "expert": expert,
                    "value": score,
                    "note": row.get("note") or "",
                    "created_at": row.get("updated_at") or datetime.now(timezone.utc).isoformat(),
                })
        self._set(key, entries)
        return entries

    def manual_nps(self, month):
        """Aggregate all manual NPS entries by expert.

        `value` is the arithmetic mean of all entered ratings for the expert.
        `count` is the number of ratings. Entries are preserved for history.
        """
        entries = self._nps_entries(month)
        grouped = {}
        for row in entries:
            expert = str(row.get("expert") or "").strip()
            if not expert:
                continue
            x = grouped.setdefault(expert, {"values": [], "entries": []})
            try:
                score = float(row.get("value"))
            except Exception:
                continue
            x["values"].append(score)
            x["entries"].append(row)
        out = {}
        for expert, x in grouped.items():
            vals = x["values"]
            rows = sorted(x["entries"], key=lambda r: str(r.get("created_at") or ""), reverse=True)
            out[expert] = {
                "value": round(sum(vals) / len(vals), 2) if vals else 0,
                "count": len(vals),
                "note": rows[0].get("note") if rows else "",
                "updated_at": rows[0].get("created_at") if rows else "",
                "entries": rows,
            }
        return out

    def add_manual_nps(self, month, expert, value, note=""):
        entries = list(self._nps_entries(month))
        entries.append({
            "id": str(uuid.uuid4()),
            "expert": expert,
            "value": float(value),
            "note": note or "",
            "created_at": datetime.now(timezone.utc).isoformat(),
        })
        self._set(f"nps_entries:{month}", entries)

    def delete_manual_nps(self, month, entry_id):
        entries = [x for x in self._nps_entries(month) if str(x.get("id")) != str(entry_id)]
        self._set(f"nps_entries:{month}", entries)

    # Backward-compatible method name used by earlier code.
    def set_manual_nps(self, month, expert, value, note=""):
        self.add_manual_nps(month, expert, value, note)

    # ---------- Generic settings ----------
    def _settings(self):
        value = self._get("settings", {})
        return value if isinstance(value, dict) else {}

    def get_setting(self, key, default=""):
        return self._settings().get(key, default)

    def set_setting(self, key, value):
        data = self._settings()
        data[key] = value
        self._set("settings", data)
