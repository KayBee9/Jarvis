alter table conversations
    add column if not exists last_consolidated_message_id uuid;
