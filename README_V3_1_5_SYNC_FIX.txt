MAVIS Operational Dashboard v3.1.5 — sync fix

Replace/add these files in the repository:
1. app/fixed_main.py            ADD
2. app/static/sync-fix.js       ADD
3. Dockerfile                   REPLACE
4. app/static/index.html        EDIT: after the existing
   <script src="/static/app.js?v=3.1.4"></script>
   add:
   <script src="/static/sync-fix.js?v=3.1.5"></script>

Why:
- background sync errors were swallowed;
- /api/snapshot returned 202 forever;
- frontend retried every 2.5 seconds forever;
- the loading caption could use the wrong preset label.

After deploy:
- /health must show version 3.1.5;
- if Bitrix calculation fails, the UI shows the actual error instead of spinning forever;
- initial polling stops after ~30 seconds and offers a Retry button;
- cached snapshots remain immediately usable.
