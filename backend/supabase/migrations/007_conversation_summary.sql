alter table conversations
    add column if not exists summary text;

alter table conversations
    add column if not exists last_summarized_message_id uuid;