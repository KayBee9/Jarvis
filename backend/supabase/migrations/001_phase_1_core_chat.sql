create extension if not exists pgcrypto;

create table if not exists conversations (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null,
  title text,
  last_response_id text,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create table if not exists messages (
  id uuid primary key default gen_random_uuid(),
  conversation_id uuid not null references conversations(id) on delete cascade,
  user_id uuid not null,
  role text not null check (role in ('user', 'assistant', 'system')),
  content text not null,
  created_at timestamptz not null default now()
);

create index if not exists conversations_user_updated_idx
  on conversations (user_id, updated_at desc);

create index if not exists messages_conversation_created_idx
  on messages (conversation_id, created_at asc);

alter table conversations enable row level security;
alter table messages enable row level security;

create policy "Users can read own conversations"
  on conversations for select
  using (auth.uid() = user_id);

create policy "Users can insert own conversations"
  on conversations for insert
  with check (auth.uid() = user_id);

create policy "Users can update own conversations"
  on conversations for update
  using (auth.uid() = user_id)
  with check (auth.uid() = user_id);

create policy "Users can read own messages"
  on messages for select
  using (auth.uid() = user_id);

create policy "Users can insert own messages"
  on messages for insert
  with check (auth.uid() = user_id);
