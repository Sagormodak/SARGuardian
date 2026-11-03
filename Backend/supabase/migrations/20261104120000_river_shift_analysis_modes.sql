-- Add two explicit RiverShift analysis modes while preserving existing Event-Based jobs.
begin;
alter table public.river_shift_jobs
  add column analysis_mode text not null default 'event_based'
  check (analysis_mode in ('general_scan', 'event_based'));
alter table public.river_shift_jobs alter column event_date drop not null;
alter table public.river_shift_jobs drop constraint river_shift_jobs_check1;
alter table public.river_shift_jobs
  add constraint river_shift_jobs_analysis_mode_event_date_check
  check (
    (analysis_mode = 'general_scan' and event_date is null)
    or
    (analysis_mode = 'event_based' and event_date between start_date and end_date)
  );
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
    or new.analysis_mode is distinct from old.analysis_mode
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
  if old.state in ('succeeded', 'failed', 'cancelled')
    and (to_jsonb(new) - 'updated_at') is distinct from (to_jsonb(old) - 'updated_at') then
    raise exception 'terminal RiverShift jobs are immutable';
  end if;
  new.updated_at = now();
  return new;
end;
$$;
comment on column public.river_shift_jobs.analysis_mode is
  'general_scan: compare dates in a window without an event date; event_based: explicit user-supplied event date.';
commit;
