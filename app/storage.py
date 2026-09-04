import sqlite3
from pathlib import Path

class Storage:
    def __init__(self,path:Path):
        self.path=path
        self._init()
    def connect(self):
        c=sqlite3.connect(self.path)
        c.row_factory=sqlite3.Row
        return c
    def _init(self):
        with self.connect() as c:
            c.execute("""
            CREATE TABLE IF NOT EXISTS plans_v2(
              month TEXT NOT NULL,
              scope TEXT NOT NULL,
              context_type TEXT NOT NULL DEFAULT 'overall',
              context_key TEXT NOT NULL DEFAULT '',
              metric TEXT NOT NULL,
              value REAL NOT NULL DEFAULT 0,
              PRIMARY KEY(month,scope,context_type,context_key,metric)
            )""")
            c.execute("""
            CREATE TABLE IF NOT EXISTS field_mapping(
              name TEXT PRIMARY KEY,
              field_code TEXT NOT NULL DEFAULT ''
            )""")
            c.commit()
    def get_plans(self,month,scope=None,context_type=None,context_key=None):
        sql="SELECT * FROM plans_v2 WHERE month=?"
        args=[month]
        if scope is not None:
            sql+=" AND scope=?"; args.append(scope)
        if context_type is not None:
            sql+=" AND context_type=?"; args.append(context_type)
        if context_key is not None:
            sql+=" AND context_key=?"; args.append(context_key)
        with self.connect() as c:
            rows=[dict(r) for r in c.execute(sql,args)]
        return rows
    def plan_dict(self,month):
        out={}
        for r in self.get_plans(month):
            key=f"{r['scope']}|{r['context_type']}|{r['context_key']}"
            out.setdefault(key,{})[r["metric"]]=float(r["value"] or 0)
        return out
    def set_plans(self,month,scope,context_type,context_key,values):
        with self.connect() as c:
            for metric,value in values.items():
                try: value=float(value or 0)
                except: continue
                c.execute("""INSERT INTO plans_v2(month,scope,context_type,context_key,metric,value)
                VALUES(?,?,?,?,?,?)
                ON CONFLICT(month,scope,context_type,context_key,metric)
                DO UPDATE SET value=excluded.value""",
                (month,scope,context_type,context_key,metric,value))
            c.commit()
    def get_mappings(self):
        with self.connect() as c:
            return {r["name"]:r["field_code"] for r in c.execute("SELECT * FROM field_mapping")}
    def set_mapping(self,name,field_code):
        with self.connect() as c:
            c.execute("""INSERT INTO field_mapping(name,field_code) VALUES(?,?)
            ON CONFLICT(name) DO UPDATE SET field_code=excluded.field_code""",(name,field_code or ""))
            c.commit()
