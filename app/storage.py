import json
import sqlite3
import uuid
from calendar import monthrange
from datetime import datetime, timedelta, timezone
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
        if self.remote_enabled:
            return "Supabase" if not self.last_remote_error else "Supabase (fallback SQLite)"
        return "SQLite persistent disk" if str(self.path).startswith("/var/data/") else "SQLite local"

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

    # ---------- Durable dashboard snapshots ----------
    def snapshot_cache(self, cache_key: str):
        value=self._get(f"snapshot_cache:{cache_key}",{})
        return value if isinstance(value,dict) else {}

    def set_snapshot_cache(self, cache_key: str, snapshot: dict):
        self._set(f"snapshot_cache:{cache_key}",{
            "snapshot":snapshot,
            "saved_at":datetime.now(timezone.utc).isoformat(),
        })

    def detail_snapshot_cache(self, cache_key: str):
        value=self._get(f"detail_snapshot_cache:{cache_key}",{})
        return value if isinstance(value,dict) else {}

    def set_detail_snapshot_cache(self, cache_key: str, details: dict):
        self._set(f"detail_snapshot_cache:{cache_key}",{
            "details":details,
            "saved_at":datetime.now(timezone.utc).isoformat(),
        })

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

    # ---------- Monthly stuck-deal baselines ----------
    def dormant_baseline(self, month: str):
        value = self._get(f"dormant_baseline:{month}", {})
        return value if isinstance(value, dict) else {}

    def set_dormant_baseline(self, month: str, value: dict):
        self._set(f"dormant_baseline:{month}", value)

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

    # ---------- Key task owners ----------
    def key_task_team(self):
        value = self._get("key_task_team", [])
        if not isinstance(value, list):
            return []
        out = []
        seen = set()
        for row in value:
            if not isinstance(row, dict):
                continue
            user_id = str(row.get("id") or "").strip()
            name = str(row.get("name") or "").strip()
            if not user_id or not name or user_id in seen:
                continue
            seen.add(user_id)
            out.append({"id": user_id, "name": name})
        return out

    def add_key_task_member(self, user_id, name):
        team = self.key_task_team()
        user_id, name = str(user_id or "").strip(), str(name or "").strip()
        if user_id and name and all(row["id"] != user_id for row in team):
            team.append({"id": user_id, "name": name})
        self._set("key_task_team", team)

    def remove_key_task_member(self, user_id):
        user_id = str(user_id or "").strip()
        self._set("key_task_team", [row for row in self.key_task_team() if row["id"] != user_id])

    def key_task_cache(self, cache_key):
        value = self._get(f"key_task_cache:{cache_key}", {})
        return value if isinstance(value, dict) else {}

    def set_key_task_cache(self, cache_key, value):
        self._set(f"key_task_cache:{cache_key}", value)

    # ---------- Dashboard-owned key tasks ----------
    def manual_key_tasks(self):
        value = self._get("manual_key_tasks", [])
        if not isinstance(value, list):
            return []
        out = []
        for row in value:
            if not isinstance(row, dict):
                continue
            task_id = str(row.get("id") or "").strip()
            title = str(row.get("title") or "").strip()
            responsible_id = str(row.get("responsible_id") or "").strip()
            deadline = str(row.get("deadline") or "").strip()
            if not task_id or not title or not responsible_id:
                continue
            out.append({
                "id": task_id,
                "title": title,
                "responsible_id": responsible_id,
                "deadline": deadline,
                "priority": "high" if str(row.get("priority") or "").lower() == "high" else "normal",
                "created_at": str(row.get("created_at") or ""),
                "project_id": str(row.get("project_id") or ""),
                "executor_ids": [str(item).strip() for item in (row.get("executor_ids") or []) if str(item).strip()] if isinstance(row.get("executor_ids"), list) else [],
                "status": str(row.get("status") or ""),
                "description": str(row.get("description") or "")[:3000],
                "updated_at": str(row.get("updated_at") or ""),
                "created_by_profile_id": str(row.get("created_by_profile_id") or ""),
                "completed_at": str(row.get("completed_at") or ""),
                "recurrence": str(row.get("recurrence") or "none"),
                "recurrence_spawned_at": str(row.get("recurrence_spawned_at") or ""),
            })
        return out

    def add_manual_key_task(self, row):
        title = str((row or {}).get("title") or "").strip()
        responsible_id = str((row or {}).get("responsible_id") or "").strip()
        deadline = str((row or {}).get("deadline") or "").strip()
        if not title:
            raise ValueError("Укажите название задачи")
        if not responsible_id:
            raise ValueError("Выберите сотрудника")
        if deadline:
            try:
                datetime.strptime(deadline, "%Y-%m-%d")
            except ValueError as exc:
                raise ValueError("Дата задачи должна быть в формате YYYY-MM-DD") from exc
        task = {
            "id": uuid.uuid4().hex,
            "title": title[:500],
            "responsible_id": responsible_id,
            "deadline": deadline,
            "priority": "high" if str((row or {}).get("priority") or "").lower() == "high" else "normal",
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        tasks = self.manual_key_tasks()
        tasks.append(task)
        self._set("manual_key_tasks", tasks)
        return task

    def remove_manual_key_task(self, task_id):
        task_id = str(task_id or "").strip()
        tasks = self.manual_key_tasks()
        kept = [row for row in tasks if row["id"] != task_id]
        if len(kept) == len(tasks):
            return False
        self._set("manual_key_tasks", kept)
        return True

    # ---------- Dashboard task workspace ----------
    # These profiles are deliberately not dashboard accounts. They are only
    # names used to sign and assign manually maintained dashboard tasks.
    def task_profiles(self):
        defaults = [
            {"id": "task-profile-tanya", "name": "Таня", "active": True},
            {"id": "task-profile-sasha", "name": "Саша", "active": True},
            {"id": "task-profile-anya", "name": "Аня", "active": True},
            {"id": "task-profile-ira", "name": "Ира", "active": True},
            {"id": "task-profile-victoria", "name": "Виктория", "active": True},
        ]
        value = self._get("task_workspace_profiles", defaults)
        if not isinstance(value, list):
            value = defaults
        out, seen = [], set()
        for row in value:
            if not isinstance(row, dict):
                continue
            profile_id = str(row.get("id") or "").strip()
            name = str(row.get("name") or "").strip()
            if not profile_id or not name or profile_id in seen:
                continue
            seen.add(profile_id)
            out.append({
                "id": profile_id,
                "name": name[:120],
                "active": bool(row.get("active", True)),
                "created_at": str(row.get("created_at") or ""),
                "deleted_at": str(row.get("deleted_at") or ""),
            })
        return out

    def add_task_profile(self, name):
        name = str(name or "").strip()
        if not name:
            raise ValueError("Укажите имя сотрудника")
        if len(name) > 120:
            raise ValueError("Имя не должно быть длиннее 120 символов")
        profiles = self.task_profiles()
        current = next((row for row in profiles if row["name"].casefold() == name.casefold()), None)
        if current:
            if not current["active"]:
                current["active"] = True
                current["deleted_at"] = ""
                self._set("task_workspace_profiles", profiles)
            return current
        profile = {"id": f"task-profile-{uuid.uuid4().hex}", "name": name, "active": True,
                   "created_at": datetime.now(timezone.utc).isoformat(), "deleted_at": ""}
        profiles.append(profile)
        self._set("task_workspace_profiles", profiles)
        return profile

    def deactivate_task_profile(self, profile_id):
        profile_id = str(profile_id or "").strip()
        profiles, found = self.task_profiles(), None
        for row in profiles:
            if row["id"] == profile_id:
                row["active"] = False
                row["deleted_at"] = datetime.now(timezone.utc).isoformat()
                found = row
                break
        if found:
            self._set("task_workspace_profiles", profiles)
        return found

    def task_projects(self):
        value = self._get("task_workspace_projects", [])
        if not isinstance(value, list):
            return []
        out, seen = [], set()
        for row in value:
            if not isinstance(row, dict):
                continue
            project_id = str(row.get("id") or "").strip()
            name = str(row.get("name") or "").strip()
            if not project_id or not name or project_id in seen:
                continue
            seen.add(project_id)
            out.append({"id": project_id, "name": name[:160], "archived": bool(row.get("archived")),
                        "created_at": str(row.get("created_at") or ""), "archived_at": str(row.get("archived_at") or "")})
        return out

    def add_task_project(self, name):
        name = str(name or "").strip()
        if not name:
            raise ValueError("Укажите название проекта")
        if len(name) > 160:
            raise ValueError("Название проекта не должно быть длиннее 160 символов")
        projects = self.task_projects()
        if any(row["name"].casefold() == name.casefold() for row in projects):
            raise ValueError("Такой проект уже есть")
        project = {"id": f"task-project-{uuid.uuid4().hex}", "name": name, "archived": False,
                   "created_at": datetime.now(timezone.utc).isoformat(), "archived_at": ""}
        projects.append(project)
        self._set("task_workspace_projects", projects)
        return project

    def archive_task_project(self, project_id, archived=True):
        project_id = str(project_id or "").strip()
        projects, found = self.task_projects(), None
        for row in projects:
            if row["id"] == project_id:
                row["archived"] = bool(archived)
                row["archived_at"] = datetime.now(timezone.utc).isoformat() if archived else ""
                found = row
                break
        if found:
            self._set("task_workspace_projects", projects)
        return found

    def workspace_tasks(self):
        """Return legacy manual tasks in the richer workspace shape without data loss."""
        profiles = {row["id"]: row for row in self.task_profiles()}
        legacy_names = {row["id"]: row["name"] for row in self.key_task_team()}
        out = []
        for row in self.manual_key_tasks():
            responsible_id = str(row.get("responsible_id") or "").strip()
            executor_ids = row.get("executor_ids")
            if not isinstance(executor_ids, list):
                executor_ids = [responsible_id] if responsible_id else []
            executor_ids = [str(value).strip() for value in executor_ids if str(value).strip()]
            status = str(row.get("status") or "in_progress")
            if status not in {"new", "in_progress", "review", "done"}:
                status = "in_progress"
            out.append({
                **row,
                "project_id": str(row.get("project_id") or ""),
                "executor_ids": list(dict.fromkeys(executor_ids)),
                "status": status,
                "description": str(row.get("description") or "")[:3000],
                "updated_at": str(row.get("updated_at") or row.get("created_at") or ""),
                "created_by_profile_id": str(row.get("created_by_profile_id") or ""),
                "completed_at": str(row.get("completed_at") or ""),
                "recurrence": str(row.get("recurrence") or "none"),
                "recurrence_spawned_at": str(row.get("recurrence_spawned_at") or ""),
                "legacy_responsible_name": legacy_names.get(responsible_id, ""),
                "profile_exists": responsible_id in profiles,
            })
        return out

    def add_workspace_task(self, row):
        values = dict(row or {})
        values["executor_ids"] = values.get("executor_ids") or ([values.get("responsible_id")] if values.get("responsible_id") else [])
        values["status"] = values.get("status") or "new"
        values["recurrence"] = str(values.get("recurrence") or "none")
        if values["recurrence"] not in {"none", "weekly", "monthly"}:
            raise ValueError("Неизвестный режим повторения")
        task = self.add_manual_key_task(values)
        all_tasks = self.manual_key_tasks()
        for item in all_tasks:
            if item["id"] == task["id"]:
                item.update({
                    "project_id": str(values.get("project_id") or ""),
                    "executor_ids": [str(value).strip() for value in values["executor_ids"] if str(value).strip()],
                    "status": str(values["status"]),
                    "description": str(values.get("description") or "")[:3000],
                    "created_by_profile_id": str(values.get("created_by_profile_id") or ""),
                    "updated_at": datetime.now(timezone.utc).isoformat(),
                    "completed_at": datetime.now(timezone.utc).isoformat() if values["status"] == "done" else "",
                    "recurrence": str(values.get("recurrence") or "none"),
                    "recurrence_spawned_at": "",
                })
                task = item
                break
        self._set("manual_key_tasks", all_tasks)
        return task

    def update_workspace_task(self, task_id, values):
        task_id = str(task_id or "").strip()
        tasks = self.manual_key_tasks()
        allowed = {"title", "responsible_id", "deadline", "priority", "project_id", "executor_ids", "status", "description", "recurrence"}
        for row in tasks:
            if row["id"] != task_id:
                continue
            for key, value in (values or {}).items():
                if key not in allowed:
                    continue
                if key == "title":
                    value = str(value or "").strip()
                    if not value:
                        raise ValueError("Укажите название задачи")
                    row[key] = value[:500]
                elif key == "deadline":
                    value = str(value or "").strip()
                    if value:
                        try:
                            datetime.strptime(value, "%Y-%m-%d")
                        except ValueError as exc:
                            raise ValueError("Дата задачи должна быть в формате YYYY-MM-DD") from exc
                    row[key] = value
                elif key == "priority":
                    row[key] = "high" if str(value).lower() == "high" else "normal"
                elif key == "status":
                    value = str(value or "")
                    if value not in {"new", "in_progress", "review", "done"}:
                        raise ValueError("Неизвестный статус задачи")
                    row[key] = value
                    row["completed_at"] = datetime.now(timezone.utc).isoformat() if value == "done" else ""
                elif key == "executor_ids":
                    row[key] = list(dict.fromkeys(str(item).strip() for item in (value or []) if str(item).strip()))
                elif key == "description":
                    row[key] = str(value or "")[:3000]
                elif key == "recurrence":
                    value = str(value or "none")
                    if value not in {"none", "weekly", "monthly"}:
                        raise ValueError("Неизвестный режим повторения")
                    row[key] = value
                else:
                    row[key] = str(value or "").strip()
            row["updated_at"] = datetime.now(timezone.utc).isoformat()
            self._set("manual_key_tasks", tasks)
            return row
        return None

    def workspace_task(self, task_id):
        task_id = str(task_id or "").strip()
        return next((row for row in self.workspace_tasks() if row["id"] == task_id), None)

    def task_comments(self, task_id):
        value = self._get(f"task_comments:{str(task_id or '').strip()}", [])
        if not isinstance(value, list):
            return []
        out = []
        for row in value:
            if not isinstance(row, dict):
                continue
            comment_id = str(row.get("id") or "").strip()
            text = str(row.get("text") or "").strip()
            if not comment_id or not text:
                continue
            out.append({
                "id": comment_id,
                "text": text[:3000],
                "author_profile_id": str(row.get("author_profile_id") or ""),
                "author_name": str(row.get("author_name") or "Команда")[:120],
                "created_at": str(row.get("created_at") or ""),
            })
        return out

    def add_task_comment(self, task_id, text, author_profile_id, author_name):
        task_id, text = str(task_id or "").strip(), str(text or "").strip()
        if not task_id:
            raise ValueError("Не указана задача")
        if not text:
            raise ValueError("Напишите комментарий")
        if len(text) > 3000:
            raise ValueError("Комментарий не должен быть длиннее 3000 символов")
        comments = self.task_comments(task_id)
        row = {
            "id": uuid.uuid4().hex,
            "text": text,
            "author_profile_id": str(author_profile_id or ""),
            "author_name": str(author_name or "Команда")[:120],
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        comments.append(row)
        self._set(f"task_comments:{task_id}", comments)
        return row

    def task_activity(self, task_id):
        value = self._get(f"task_activity:{str(task_id or '').strip()}", [])
        if not isinstance(value, list):
            return []
        out = []
        for row in value:
            if not isinstance(row, dict):
                continue
            event_id = str(row.get("id") or "").strip()
            text = str(row.get("text") or "").strip()
            if not event_id or not text:
                continue
            out.append({
                "id": event_id,
                "kind": str(row.get("kind") or "updated"),
                "text": text[:500],
                "author_profile_id": str(row.get("author_profile_id") or ""),
                "author_name": str(row.get("author_name") or "Команда")[:120],
                "created_at": str(row.get("created_at") or ""),
            })
        return out

    def add_task_activity(self, task_id, text, author_profile_id="", author_name="Команда", kind="updated"):
        task_id, text = str(task_id or "").strip(), str(text or "").strip()
        if not task_id or not text:
            return None
        events = self.task_activity(task_id)
        row = {
            "id": uuid.uuid4().hex,
            "kind": str(kind or "updated")[:40],
            "text": text[:500],
            "author_profile_id": str(author_profile_id or ""),
            "author_name": str(author_name or "Команда")[:120],
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        events.append(row)
        self._set(f"task_activity:{task_id}", events[-300:])
        return row

    def create_next_recurrence_task(self, task_id):
        """Create one future copy after the first completion of a repeating task."""
        task_id = str(task_id or "").strip()
        tasks = self.manual_key_tasks()
        source = next((row for row in tasks if row["id"] == task_id), None)
        if not source or source.get("status") != "done" or source.get("recurrence") not in {"weekly", "monthly"}:
            return None
        if source.get("recurrence_spawned_at") or not source.get("deadline"):
            return None
        try:
            deadline = datetime.strptime(source["deadline"], "%Y-%m-%d").date()
        except ValueError:
            return None
        if source["recurrence"] == "weekly":
            next_deadline = deadline + timedelta(days=7)
        else:
            year, month = deadline.year + (deadline.month == 12), (deadline.month % 12) + 1
            next_deadline = deadline.replace(year=year, month=month, day=min(deadline.day, monthrange(year, month)[1]))
        now = datetime.now(timezone.utc).isoformat()
        source["recurrence_spawned_at"] = now
        clone = {
            "id": uuid.uuid4().hex,
            "title": source["title"],
            "responsible_id": source["responsible_id"],
            "deadline": next_deadline.isoformat(),
            "priority": source.get("priority") or "normal",
            "created_at": now,
            "project_id": source.get("project_id") or "",
            "executor_ids": list(source.get("executor_ids") or [source["responsible_id"]]),
            "status": "new",
            "description": source.get("description") or "",
            "updated_at": now,
            "created_by_profile_id": source.get("created_by_profile_id") or "",
            "completed_at": "",
            "recurrence": source["recurrence"],
            "recurrence_spawned_at": "",
        }
        tasks.append(clone)
        self._set("manual_key_tasks", tasks)
        return clone

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
