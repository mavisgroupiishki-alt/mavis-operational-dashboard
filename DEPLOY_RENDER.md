# Deploy v2.4 on Render Free

1. Replace files in the existing GitHub repository with the contents of this project.
2. Render auto-deploys `main`.
3. In Render -> Environment verify existing Bitrix variables and add:
   - `SUPABASE_URL`
   - `SUPABASE_KEY`
4. After deploy check `/health`.
5. `storage` must be `Supabase`.

## Existing service warning

If the current service was originally created with a persistent disk / Starter instance, `render.yaml` cannot always downgrade that existing resource automatically.

After Supabase works:
- remove the Render persistent disk;
- choose Free instance;
- keep the web service public;
- keep the uptime monitor on `/health` if you want to avoid spin-down.

The app does not need Render disk when Supabase is configured.
