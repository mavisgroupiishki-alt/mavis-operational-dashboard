const CACHE_NAME="mavis-operational-v3.1.2";
const SHELL=["/","/static/styles.css?v=3.1.1","/static/app.js?v=3.1.2","/static/icon.svg","/manifest.webmanifest"];
const SNAPSHOT_PATHS=["/api/snapshot","/api/marketing","/api/crm-audit"];

async function putIfSuccessful(cache,request,response){
  if(response&&response.ok)await cache.put(request,response.clone());
  return response;
}

async function networkFirst(request){
  const cache=await caches.open(CACHE_NAME);
  try{return await putIfSuccessful(cache,request,await fetch(request));}
  catch(error){
    const cached=await cache.match(request);
    if(!cached)throw error;
    const headers=new Headers(cached.headers);headers.set("X-Mavis-Cache","offline");
    return new Response(await cached.blob(),{status:cached.status,statusText:cached.statusText,headers});
  }
}

self.addEventListener("install",event=>event.waitUntil((async()=>{
  const cache=await caches.open(CACHE_NAME);
  await Promise.all(SHELL.map(async url=>{try{await putIfSuccessful(cache,url,await fetch(url,{cache:"reload"}));}catch(error){}}));
  await self.skipWaiting();
})()));
self.addEventListener("activate",event=>event.waitUntil((async()=>{
  await Promise.all((await caches.keys()).filter(key=>key.startsWith("mavis-operational-")&&key!==CACHE_NAME).map(key=>caches.delete(key)));
  await self.clients.claim();
})()));
self.addEventListener("fetch",event=>{
  const request=event.request,url=new URL(request.url);
  if(request.method!=="GET"||url.origin!==self.location.origin)return;
  if(request.mode==="navigate"||SNAPSHOT_PATHS.includes(url.pathname)){event.respondWith(networkFirst(request));return;}
  if(url.pathname.startsWith("/static/")||url.pathname==="/manifest.webmanifest"){
    event.respondWith((async()=>{const cache=await caches.open(CACHE_NAME);const cached=await cache.match(request);if(cached){fetch(request).then(response=>putIfSuccessful(cache,request,response)).catch(()=>{});return cached;}return networkFirst(request);})());
  }
});
