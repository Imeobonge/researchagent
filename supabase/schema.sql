create table if not exists public.researches (
    id text primary key,
    topic text not null,
    created_at timestamptz not null default now(),
    date_mode text not null,
    start_date date,
    end_date date,
    requested_sources integer not null,
    analyzed_sources integer not null,
    sections jsonb not null default '[]'::jsonb,
    sources jsonb not null default '[]'::jsonb,
    report_markdown text not null,
    synthesis_mode text not null,
    elapsed_seconds double precision not null default 0
);

alter table public.researches enable row level security;
revoke all on table public.researches from anon, authenticated;

-- Astra accesses this table only from server-side Python with SUPABASE_SECRET_KEY.
-- Do not expose that key in source control or browser code.

create index if not exists researches_created_at_idx
    on public.researches (created_at desc);
