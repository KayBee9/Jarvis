-- Pending memory changes awaiting user approval.
-- ADD and SKIP are executed immediately; REPLACE and DELETE land here.

create table if not exists pending_memory_changes (
  id uuid primary key default gen_random_uuid(),
  action text not null check (action in ('REPLACE', 'DELETE')),
  target_memory_id uuid not null references memories(id) on delete cascade,
  target_content text not null,
  proposed_content text,
  created_at timestamptz not null default now()
);

create index if not exists pending_memory_changes_created_idx
  on pending_memory_changes (created_at desc);
