import sqlite3
from pathlib import Path
from datetime import datetime

DEFAULT_MANAGERS = ["Ирина Богомольцева", "Роман Авсеенко"]
DEFAULT_EXPERTS = ["Мария Баженова", "Татьяна Куровская"]

class Storage:
    def __init__(self,path:Path):
        self.path=path
        self.path.parent.mkdir(parents=True, exist_ok=True)
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
            c.execute("""
            CREATE TABLE IF NOT EXISTS team_members(
              role TEXT NOT NULL,
              name TEXT NOT NULL,
              sort_order INTEGER NOT NULL DEFAULT 100,
              PRIMARY KEY(role,name)
            )""")
            c.execute("""
            CREATE TABLE IF NOT EXISTS tile_comments(
              month TEXT NOT NULL,
              scope TEXT NOT NULL,
              metric TEXT NOT NULL,
              comment TEXT NOT NULL DEFAULT '',
              updated_at TEXT NOT NULL DEFAULT '',
              PRIMARY KEY(month,scope,metric)
            )""")
            c.execute("""
            CREATE TABLE IF NOT EXISTS manual_nps(
              month TEXT NOT NULL,
              expert TEXT NOT NULL,
              value REAL NOT NULL,
              note TEXT NOT NULL DEFAULT '',
              updated_at TEXT NOT NULL DEFAULT '',
              PRIMARY KEY(month,expert)
            )""")
            c.execute("""
            CREATE TABLE IF NOT EXISTS app_settings(
              key TEXT PRIMARY KEY,
              value TEXT NOT NULL DEFAULT ''
            )""")
            c.commit()
        self._seed_team()
    def _seed_team(self):
        with self.connect() as c:
            for i,n in enumerate(DEFAULT_MANAGERS):
                c.execute("INSERT OR IGNORE INTO team_members(role,name,sort_order) VALUES('manager',?,?)",(n,i))
            for i,n in enumerate(DEFAULT_EXPERTS):
                c.execute("INSERT OR IGNORE INTO team_members(role,name,sort_order) VALUES('expert',?,?)",(n,i))
            c.commit()
    def get_plans(self,month,scope=None,context_type=None,context_key=None):
        sql="SELECT * FROM plans_v2 WHERE month=?"; args=[month]
        if scope is not None: sql+=" AND scope=?"; args.append(scope)
        if context_type is not None: sql+=" AND context_type=?"; args.append(context_type)
        if context_key is not None: sql+=" AND context_key=?"; args.append(context_key)
        with self.connect() as c: return [dict(r) for r in c.execute(sql,args)]
    def plan_dict(self,month):
        out={}
        for r in self.get_plans(month):
            key=f"{r['scope']}|{r['context_type']}|{r['context_key']}"
            out.setdefault(key,{})[r['metric']]=float(r['value'] or 0)
        return out
    def set_plans(self,month,scope,context_type,context_key,values):
        with self.connect() as c:
            for metric,value in values.items():
                try:value=float(value or 0)
                except:continue
                c.execute("""INSERT INTO plans_v2(month,scope,context_type,context_key,metric,value)
                VALUES(?,?,?,?,?,?) ON CONFLICT(month,scope,context_type,context_key,metric)
                DO UPDATE SET value=excluded.value""",(month,scope,context_type,context_key,metric,value))
            c.commit()
    def get_mappings(self):
        with self.connect() as c:return {r['name']:r['field_code'] for r in c.execute('SELECT * FROM field_mapping')}
    def set_mapping(self,name,field_code):
        with self.connect() as c:
            c.execute("""INSERT INTO field_mapping(name,field_code) VALUES(?,?)
            ON CONFLICT(name) DO UPDATE SET field_code=excluded.field_code""",(name,field_code or ''));c.commit()
    def team(self):
        out={'managers':[],'experts':[]}
        with self.connect() as c:
            rows=list(c.execute('SELECT role,name FROM team_members ORDER BY role,sort_order,name'))
        for r in rows:
            if r['role']=='manager':out['managers'].append(r['name'])
            elif r['role']=='expert':out['experts'].append(r['name'])
        return out
    def add_team_member(self,role,name):
        if role not in {'manager','expert'}:raise ValueError('bad role')
        with self.connect() as c:
            m=c.execute('SELECT COALESCE(MAX(sort_order),0)+1 FROM team_members WHERE role=?',(role,)).fetchone()[0]
            c.execute('INSERT OR IGNORE INTO team_members(role,name,sort_order) VALUES(?,?,?)',(role,name,m));c.commit()
    def remove_team_member(self,role,name):
        with self.connect() as c:c.execute('DELETE FROM team_members WHERE role=? AND name=?',(role,name));c.commit()
    def comments(self,month):
        with self.connect() as c:rows=list(c.execute('SELECT scope,metric,comment,updated_at FROM tile_comments WHERE month=?',(month,)))
        return {f"{r['scope']}|{r['metric']}":{'comment':r['comment'],'updated_at':r['updated_at']} for r in rows}
    def set_comment(self,month,scope,metric,comment):
        ts=datetime.utcnow().isoformat(timespec='seconds')+'Z'
        with self.connect() as c:
            c.execute("""INSERT INTO tile_comments(month,scope,metric,comment,updated_at) VALUES(?,?,?,?,?)
            ON CONFLICT(month,scope,metric) DO UPDATE SET comment=excluded.comment,updated_at=excluded.updated_at""",(month,scope,metric,comment or '',ts));c.commit()
    def manual_nps(self,month):
        with self.connect() as c:rows=list(c.execute('SELECT expert,value,note,updated_at FROM manual_nps WHERE month=?',(month,)))
        return {r['expert']:{'value':float(r['value']),'note':r['note'],'updated_at':r['updated_at']} for r in rows}
    def set_manual_nps(self,month,expert,value,note=''):
        ts=datetime.utcnow().isoformat(timespec='seconds')+'Z'
        with self.connect() as c:
            c.execute("""INSERT INTO manual_nps(month,expert,value,note,updated_at) VALUES(?,?,?,?,?)
            ON CONFLICT(month,expert) DO UPDATE SET value=excluded.value,note=excluded.note,updated_at=excluded.updated_at""",(month,expert,float(value),note or '',ts));c.commit()
    def get_setting(self,key,default=''):
        with self.connect() as c:r=c.execute('SELECT value FROM app_settings WHERE key=?',(key,)).fetchone()
        return r['value'] if r else default
    def set_setting(self,key,value):
        with self.connect() as c:
            c.execute("""INSERT INTO app_settings(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value""",(key,value or ''));c.commit()
