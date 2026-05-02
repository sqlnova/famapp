create table if not exists captures (
  id uuid primary key default gen_random_uuid(),
  family_id uuid,
  user_id uuid,
  raw_input text not null,
  input_type text not null check (input_type in ('text','audio','image','screenshot')),
  source text not null check (source in ('manual','share_extension','upload','voice')),
  status text not null default 'pending' check (status in ('pending','processed','confirmed','discarded','failed')),
  ai_result_json jsonb,
  confidence double precision,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);
create index if not exists captures_status_idx on captures(status);
create trigger captures_updated_at before update on captures for each row execute procedure set_updated_at();

create table if not exists push_tokens (
  id uuid primary key default gen_random_uuid(),
  user_id uuid,
  family_id uuid,
  platform text,
  token text not null unique,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);
create trigger push_tokens_updated_at before update on push_tokens for each row execute procedure set_updated_at();

create table if not exists capture_reminders (
  id uuid primary key default gen_random_uuid(),
  capture_id uuid references captures(id) on delete cascade,
  title text not null,
  remind_at timestamptz not null,
  status text not null default 'pending' check (status in ('pending','sent','cancelled')),
  created_at timestamptz not null default now()
);
create index if not exists capture_reminders_pending_idx on capture_reminders(remind_at) where status='pending';
