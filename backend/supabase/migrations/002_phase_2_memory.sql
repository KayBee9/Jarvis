create table if not exists memories (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null,
  content text not null,
  created_at timestamptz not null default now()
);

create index if not exists memories_user_created_idx
  on memories (user_id, created_at desc);

alter table memories enable row level security;

create policy "Users can read own memories"
  on memories for select
  using (auth.uid() = user_id);

create policy "Users can insert own memories"
  on memories for insert
  with check (auth.uid() = user_id);

create policy "Users can delete own memories"
  on memories for delete
  using (auth.uid() = user_id);