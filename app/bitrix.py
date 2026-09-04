import asyncio,time
from typing import Any,Dict,List,Tuple
from urllib.parse import urlencode,urlparse
import httpx

class BitrixError(RuntimeError): pass

def flatten(params):
    out=[]
    def add(prefix,v):
        if v is None:return
        if isinstance(v,dict):
            for k,x in v.items(): add(f"{prefix}[{k}]",x)
        elif isinstance(v,(list,tuple)):
            for x in v: out.append((f"{prefix}[]",str(x)))
        else: out.append((prefix,str(v)))
    for k,v in (params or {}).items(): add(k,v)
    return out

class BitrixClient:
    def __init__(self,webhook):
        self.webhook=webhook.rstrip("/")+"/"
        self.client=httpx.AsyncClient(timeout=50)
        self.sem=asyncio.Semaphore(8)
        self._meta=None; self._meta_at=0
    @property
    def portal(self):
        p=urlparse(self.webhook)
        return f"{p.scheme}://{p.netloc}"
    async def close(self): await self.client.aclose()
    async def call(self,method,params=None):
        if not self.webhook.startswith("http"): raise BitrixError("BITRIX_WEBHOOK не задан")
        body=urlencode(flatten(params or {})).encode()
        async with self.sem:
            r=await self.client.post(self.webhook+method+".json",content=body,
                headers={"Content-Type":"application/x-www-form-urlencoded; charset=utf-8"})
        try: p=r.json()
        except: raise BitrixError(f"{method}: HTTP {r.status_code}, не JSON")
        if r.status_code>=400 or p.get("error"):
            raise BitrixError(f"{method}: {p.get('error_description') or p.get('error') or r.status_code}")
        return p
    async def list_all(self,method,params=None,limit=None):
        start=0; items=[]; params=dict(params or {})
        while True:
            q=dict(params); q["start"]=start
            p=await self.call(method,q); result=p.get("result")
            if isinstance(result,list): batch=result
            elif isinstance(result,dict) and isinstance(result.get("items"),list): batch=result["items"]
            elif isinstance(result,dict) and isinstance(result.get("productRows"),list): batch=result["productRows"]
            else:return result
            items.extend(batch)
            if limit and len(items)>=limit:return items[:limit]
            if p.get("next") is None:break
            start=int(p["next"])
        return items
    async def deal_list(self,flt,select):
        return await self.list_all("crm.deal.list",{"order":{"ID":"ASC"},"filter":flt,"select":select})
    async def lead_list(self,flt,select):
        return await self.list_all("crm.lead.list",{"order":{"ID":"ASC"},"filter":flt,"select":select})
    async def product_rows(self,deal_id):
        try:
            p=await self.call("crm.item.productrow.list",{"filter":{"=ownerType":"D","=ownerId":int(deal_id)}})
            r=p.get("result",{})
            if isinstance(r,dict) and isinstance(r.get("productRows"),list): return r["productRows"]
        except Exception: pass
        p=await self.call("crm.deal.productrows.get",{"id":int(deal_id)})
        return p.get("result",[]) or []
    async def product_rows_many(self,deals):
        """Load product rows in Bitrix batches instead of one HTTP request per deal.
        Bitrix batch accepts up to 50 commands; 40 leaves a little safety margin.
        Falls back to individual requests only for failed batches.
        """
        ids=[str(d.get("ID")) for d in deals if d.get("ID")]
        if not ids:return {}
        out={}
        chunk_size=40
        for pos in range(0,len(ids),chunk_size):
            chunk=ids[pos:pos+chunk_size]
            cmds={f"d{i}":f"crm.deal.productrows.get?id={did}" for i,did in enumerate(chunk)}
            try:
                payload=await self.call("batch",{"halt":0,"cmd":cmds})
                result=(payload.get("result") or {}).get("result") or {}
                errors=(payload.get("result") or {}).get("result_error") or {}
                failed=[]
                for i,did in enumerate(chunk):
                    key=f"d{i}"
                    if key in errors:
                        failed.append(did)
                    else:
                        out[did]=result.get(key) or []
                if failed:
                    async def one(did):
                        try:return did,await self.product_rows(did)
                        except:return did,[]
                    out.update(dict(await asyncio.gather(*(one(x) for x in failed))))
            except Exception:
                async def one(did):
                    try:return did,await self.product_rows(did)
                    except:return did,[]
                out.update(dict(await asyncio.gather(*(one(x) for x in chunk))))
        return out
    async def meta(self,force=False):
        if self._meta and not force and time.monotonic()-self._meta_at<600:return self._meta
        users,statuses,df,lf=await asyncio.gather(
            self.list_all("user.get",{"FILTER":{"ACTIVE":True}}),
            self.list_all("crm.status.list",{"order":{"SORT":"ASC"}}),
            self.call("crm.deal.fields"),
            self.call("crm.lead.fields"))
        um={}
        for u in users or []:
            n=" ".join(x for x in [u.get("NAME"),u.get("LAST_NAME")] if x).strip()
            um[str(u.get("ID"))]=n or f"ID {u.get('ID')}"
        sm={}; sources={}; status_by_entity={}
        for s in statuses or []:
            sid=str(s.get("STATUS_ID")); ent=str(s.get("ENTITY_ID") or "")
            sm[sid]=s.get("NAME") or sid
            status_by_entity.setdefault(ent,{})[sid]=s.get("NAME") or sid
            if ent=="SOURCE": sources[sid]=s.get("NAME") or sid
        enums={}
        deal_fields=(df.get("result") or {})
        for code,m in deal_fields.items():
            if isinstance(m,dict) and m.get("items"):
                enums[code]={str(i.get("ID")):i.get("VALUE") for i in m["items"]}
        self._meta={"users":um,"statuses":sm,"status_by_entity":status_by_entity,"sources":sources,"enums":enums,
                    "deal_fields":deal_fields,"lead_fields":lf.get("result") or {}}
        self._meta_at=time.monotonic()
        return self._meta
