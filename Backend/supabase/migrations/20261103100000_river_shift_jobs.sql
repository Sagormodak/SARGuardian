-- RiverShift is an independent engine with its own job lifecycle and callback sequence.
-- It deliberately does not share displacement_jobs or Known Place request records.
begin;

create table public.river_shift_jobs (
  id uuid primary key default gen_random_uuid(),
  owner_uid text not null check (length(btrim(owner_uid)) > 0),
  idempotency_key text not null check (idempotency_key ~ '^[A-Za-z0-9._:-]{16,128}$'),
  state text not null default 'queued'
    check (state in ('queued', 'dispatching', 'running', 'succeeded', 'failed', 'cancelled')),
  stage text not null default 'queued' check (length(stage) between 1 and 80),
  aoi_wkt text not null check (length(aoi_wkt) between 20 and 100000),
  start_date date not null,
  end_date date not null check (end_date >= start_date and end_date - start_date <= 366),
  event_date date not null check (event_date between start_date and end_date),
  maturity text not null check (maturity in ('BETA', 'PROVISIONAL')),
  frequency text not null check (frequency in ('frequencyA', 'frequencyB')),
  covariance_term text not null check (covariance_term in ('HHHH', 'HVHV', 'VVVV', 'VHVH', 'RHRH', 'RVRV')),
  threshold_method text not null check (threshold_method in ('otsu', 'manual')),
  threshold_db double precision,
  request_snapshot jsonb not null,
  manifest_snapshot jsonb not null,
  request_fingerprint text not null check (request_fingerprint ~ '^[a-f0-9]{64}$'),
  github_run_id text,
  github_run_url text,
  callback_sequence integer not null default 0 check (callback_sequence between 0 and 1000),
  result_summary jsonb,
  artifact_manifest jsonb,
  error_code text,
  error_message text,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  unique (owner_uid, idempotency_key),
  check ((threshold_method = 'otsu' and threshold_db is null)
      or (threshold_method = 'manual' and threshold_db between -60 and 0))
);

create index river_shift_jobs_owner_created_idx
  on public.river_shift_jobs (owner_uid, created_at desc);
create index river_shift_jobs_state_idx
  on public.river_shift_jobs (state);

create or replace function public.enforce_river_shift_job_transition()
returns trigger language plpgsql set search_path = public as $$
begin
  if tg_op = 'INSERT' then
    if new.state <> 'queued' or new.callback_sequence <> 0 then
      raise exception 'new RiverShift jobs must start queued with callback sequence zero';
    end if;
    return new;
  end if;

  if new.state <> old.state and not (
    (old.state = 'queued' and new.state in ('dispatching', 'failed', 'cancelled')) or
    (old.state = 'dispatching' and new.state in ('running', 'failed', 'cancelled')) or
    (old.state = 'running' and new.state in ('running', 'succeeded', 'failed', 'cancelled'))
  ) then
    raise exception 'invalid RiverShift job transition: % -> %', old.state, new.state;
  end if;

  if new.owner_uid is distinct from old.owner_uid
    or new.idempotency_key is distinct from old.idempotency_key
    or new.aoi_wkt is distinct from old.aoi_wkt
    or new.start_date is distinct from old.start_date
    or new.end_date is distinct from old.end_date
    or new.event_date is distinct from old.event_date
    or new.maturity is distinct from old.maturity
    or new.frequency is distinct from old.frequency
    or new.covariance_term is distinct from old.covariance_term
    or new.threshold_method is distinct from old.threshold_method
    or new.threshold_db is distinct from old.threshold_db
    or new.request_snapshot is distinct from old.request_snapshot
    or new.manifest_snapshot is distinct from old.manifest_snapshot
    or new.request_fingerprint is distinct from old.request_fingerprint then
    raise exception 'RiverShift accepted request inputs are immutable';
  end if;

  if new.callback_sequence < old.callback_sequence
    or new.callback_sequence > old.callback_sequence + 1 then
    raise exception 'RiverShift callback sequence is invalid';
  end if;

  if old.state in ('succeeded', 'failed', 'cancelled') and new.state <> old.state then
    raise exception 'terminal RiverShift jobs are immutable';
  end if;

  new.updated_at = now();
  return new;
end;
$$;

create trigger river_shift_jobs_transition_guard
before insert or update on public.river_shift_jobs
for each row execute function public.enforce_river_shift_job_transition();

alter table public.river_shift_jobs enable row level security;
revoke all on table public.river_shift_jobs from anon, authenticated;
grant select, insert, update on table public.river_shift_jobs to service_role;
create policy river_shift_jobs_owner_read
  on public.river_shift_jobs for select to authenticated
  using ((select auth.jwt() ->> 'sub') = owner_uid);

comment on table public.river_shift_jobs is
  'Independent RiverShift NISAR GCOV engine jobs, immutable accepted requests and signed worker receipts.';
commit;
