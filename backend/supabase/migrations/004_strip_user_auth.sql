-- Strip multi-user scaffolding. Single-user mode from here on.

-- Drop RLS policies (they reference user_id)
drop policy if exists "Users can read own conversations" on conversations;
drop policy if exists "Users can insert own conversations" on conversations;
drop policy if exists "Users can update own conversations" on conversations;
drop policy if exists "Users can read own messages" on messages;
drop policy if exists "Users can insert own messages" on messages;
drop policy if exists "Users can read own memories" on memories;
drop policy if exists "Users can insert own memories" on memories;
drop policy if exists "Users can delete own memories" on memories;

-- Disable RLS — backend connects as postgres which bypasses it anyway.
alter table conversations disable row level security;
alter table messages disable row level security;
alter table memories disable row level security;

-- Drop indexes that reference user_id
drop index if exists conversations_user_updated_idx;
drop index if exists memories_user_created_idx;

-- Drop user_id columns
alter table conversations drop column if exists user_id;
alter table messages drop column if exists user_id;
alter table memories drop column if exists user_id;

-- Recreate sensible indexes without user_id
create index if not exists conversations_updated_idx on conversations (updated_at desc);
create index if not exists memories_created_idx on memories (created_at desc);