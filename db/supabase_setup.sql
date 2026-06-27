-- ============================================================================
-- RossBot — Supabase hardening SQL
-- ============================================================================
-- WHAT THIS IS
--   Supabase auto-exposes every table in the `public` schema through its Data API
--   (PostgREST) to the `anon` / `authenticated` roles. For a real-money trading bot,
--   that data (orders, fills, ledger, positions, risk_events) must NOT be publicly
--   reachable. This script locks the Data API down. It does NOT create tables.
--
-- ORDER OF OPERATIONS
--   1. Create the schema with Alembic (single source of truth = db/models.py):
--          python scripts/run_migrations.py
--      This creates all 12 tables + append-only triggers + seeds config.
--      (TimescaleDB hypertables are auto-skipped — Supabase has no timescaledb; that's fine.)
--   2. Paste THIS file into the Supabase SQL Editor and run it.
--
-- HOW THE BOT STILL HAS ACCESS
--   RossBot connects with the direct Postgres connection string (the `postgres` role).
--   The `postgres`/`service_role` roles BYPASS Row-Level Security, so the bot keeps full
--   read/write access. RLS + the revokes below only block the public anon Data API.
--
-- ALTERNATIVE (simplest): disable the Data API entirely in
--   Supabase Dashboard → Project Settings → Data API → "Exposed schemas" (remove `public`),
--   then this script is defense-in-depth. Running both is recommended.
--
-- verified: supabase.com/docs/guides/api/securing-your-api (2026-06)
-- verified: supabase.com/docs/guides/database/postgres/row-level-security (2026-06)
-- ============================================================================

begin;

-- ----------------------------------------------------------------------------
-- 1) Stop FUTURE tables/functions/sequences from being auto-granted to the API.
--    (Supabase is moving to this as the platform default; set it explicitly.)
-- ----------------------------------------------------------------------------
alter default privileges for role postgres in schema public
    revoke select, insert, update, delete on tables from anon, authenticated;

alter default privileges for role postgres in schema public
    revoke usage, select on sequences from anon, authenticated;

alter default privileges for role postgres in schema public
    revoke execute on functions from anon, authenticated;

-- ----------------------------------------------------------------------------
-- 2) Revoke privileges already granted on the CURRENT tables/sequences/functions.
-- ----------------------------------------------------------------------------
revoke all on all tables in schema public from anon, authenticated;
revoke all on all sequences in schema public from anon, authenticated;
revoke all on all functions in schema public from anon, authenticated;

-- ----------------------------------------------------------------------------
-- 3) Enable Row-Level Security on every table in `public`.
--    RLS enabled + zero policies = anon/authenticated get NOTHING (deny-by-default).
--    We intentionally create NO policies: this is a private bot, not a public app.
--    The DO-loop covers all current tables; the explicit list documents the 12 expected.
-- ----------------------------------------------------------------------------
do $$
declare
    r record;
begin
    for r in
        select tablename
        from pg_tables
        where schemaname = 'public'
    loop
        execute format('alter table public.%I enable row level security;', r.tablename);
        -- FORCE so even the table owner is subject to RLS via the Data API path.
        execute format('alter table public.%I force row level security;', r.tablename);
    end loop;
end $$;

-- Expected tables (db/models.py): symbols, bars, quotes, depth_snapshots, tape_prints,
-- signals, orders, fills, positions, ledger, risk_events, config.

commit;

-- ----------------------------------------------------------------------------
-- 4) Verification — every row should show rowsecurity = true and no anon/auth grants.
-- ----------------------------------------------------------------------------
select schemaname, tablename, rowsecurity
from pg_tables
where schemaname = 'public'
order by tablename;

-- Any rows returned here mean anon/authenticated still hold a grant (should be empty):
select grantee, table_name, privilege_type
from information_schema.role_table_grants
where table_schema = 'public'
  and grantee in ('anon', 'authenticated')
order by table_name, grantee;
