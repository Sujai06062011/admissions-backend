-- ============================================================
-- Admissions Screening Platform — Database Schema (v1)
-- Target: Postgres (Supabase)
-- Run this in Supabase SQL Editor after project creation.
-- ============================================================

create extension if not exists "uuid-ossp";

-- ============================================================
-- CORE: Tenants, Programs, Admin Users
-- ============================================================

create table tenants (
  id uuid primary key default uuid_generate_v4(),
  name text not null,
  slug text unique not null,
  created_at timestamptz default now()
);

create table programs (
  id uuid primary key default uuid_generate_v4(),
  tenant_id uuid not null references tenants(id) on delete cascade,
  name text not null,               -- e.g. "MBA Finance"
  is_active boolean default true,
  created_at timestamptz default now()
);

create table admin_users (
  id uuid primary key default uuid_generate_v4(),
  tenant_id uuid not null references tenants(id) on delete cascade,
  email text unique not null,
  full_name text,
  role text not null default 'admin',   -- admin, reviewer, super_admin
  password_hash text,   -- bcrypt; null until a password is set (no self-serve reset yet)
  created_at timestamptz default now()
);

-- ============================================================
-- STAGE 1: Applicants & Applications
-- ============================================================

create table applicants (
  id uuid primary key default uuid_generate_v4(),
  full_name text,
  email text,
  phone text,
  created_at timestamptz default now()
);

create table applications (
  id uuid primary key default uuid_generate_v4(),
  tenant_id uuid not null references tenants(id) on delete cascade,
  program_id uuid not null references programs(id) on delete cascade,
  applicant_id uuid not null references applicants(id) on delete cascade,
  status text not null default 'submitted',
  -- submitted -> under_review -> moved_to_campus -> testing_complete
  -- -> called_for_interview -> offered / rejected
  sequence_number integer not null,  -- 1-based, unique per program_id; assigned under a row lock on the program
  application_number text not null,  -- human-readable, e.g. SUJA-170399-0013; derived from name+dob+sequence_number at creation
  created_at timestamptz default now(),
  updated_at timestamptz default now()
);

create table profile_data (
  application_id uuid primary key references applications(id) on delete cascade,
  data jsonb not null default '{}',        -- OCR-prefilled + candidate-edited profile
  form_template_version text,
  updated_at timestamptz default now()
);

create table uploaded_documents (
  id uuid primary key default uuid_generate_v4(),
  application_id uuid not null references applications(id) on delete cascade,
  doc_type text not null,                  -- resume, 10th_marksheet, 12th_marksheet, ug_marksheet
  file_url text not null,
  ocr_result jsonb,
  ocr_confidence numeric,
  created_at timestamptz default now()
);

-- ============================================================
-- STAGE 2: Preferences, Matching, Admin Decisions
-- ============================================================

create table preference_configs (
  id uuid primary key default uuid_generate_v4(),
  program_id uuid not null references programs(id) on delete cascade,
  field_name text not null,                -- e.g. "10th_percentage"
  is_hard_cutoff boolean default false,
  cutoff_value numeric,                    -- used if is_hard_cutoff = true
  soft_weight numeric default 0,           -- used for ranking score
  created_at timestamptz default now()
);

create table preference_match_results (
  application_id uuid primary key references applications(id) on delete cascade,
  composite_score numeric,
  hard_pass boolean,
  reasons jsonb default '[]',              -- [{field, expected, actual, passed}]
  computed_at timestamptz default now()
);

create table admin_decisions (
  id uuid primary key default uuid_generate_v4(),
  application_id uuid not null references applications(id) on delete cascade,
  stage text not null,                     -- 'stage2_move_to_campus', 'stage3_call_for_interview', 'stage4_offer'
  decision text not null,                  -- 'approved', 'rejected', 'manual_override'
  decided_by uuid references admin_users(id),
  decided_at timestamptz default now(),
  notes text
);

-- ============================================================
-- STAGE 3: Credentials, Question Bank, Test A
-- ============================================================

create table credentials (
  application_id uuid primary key references applications(id) on delete cascade,
  temp_username text unique not null,
  temp_password_hash text not null,
  expires_at timestamptz not null,
  delivered_via text[],                    -- {'email','whatsapp'}
  login_status text default 'not_logged_in',
  created_at timestamptz default now()
);

create table question_banks (
  id uuid primary key default uuid_generate_v4(),
  program_id uuid not null references programs(id) on delete cascade,
  name text not null
);

create table questions (
  id uuid primary key default uuid_generate_v4(),
  bank_id uuid not null references question_banks(id) on delete cascade,
  category text not null,                  -- quant, verbal, logical_reasoning, english_grammar, reading_comp
  question_text text not null,
  options jsonb,                           -- ["A", "B", "C", "D"]
  correct_answer text,                     -- single-select: exact option text, or a letter label (A, B, ...)
  answer_type text not null default 'single', -- 'single' or 'multi'
  correct_answers jsonb,                   -- multi-select: ["A", "C"] — same letter/text convention as correct_answer, one per correct option
  difficulty text default 'medium',
  created_at timestamptz default now()
);

create table test_blueprints (
  id uuid primary key default uuid_generate_v4(),
  program_id uuid not null references programs(id) on delete cascade,
  category text not null,
  question_count int not null,
  duration_minutes int not null,
  pass_threshold numeric
);

create table test_a_sessions (
  application_id uuid primary key references applications(id) on delete cascade,
  generated_questions jsonb not null,      -- snapshot of question IDs + shuffled order shown
  answers jsonb default '{}',
  score numeric,
  started_at timestamptz,
  submitted_at timestamptz
);

-- ============================================================
-- STAGE 3: AI Video Interview (Test B)
-- ============================================================

create table prompt_banks (
  id uuid primary key default uuid_generate_v4(),
  program_id uuid not null references programs(id) on delete cascade,
  name text not null
);

create table prompts (
  id uuid primary key default uuid_generate_v4(),
  bank_id uuid not null references prompt_banks(id) on delete cascade,
  prompt_type text not null,               -- image, video, question
  media_url text,
  prompt_text text,
  category text,
  created_at timestamptz default now()
);

create table test_b_sessions (
  application_id uuid primary key references applications(id) on delete cascade,
  prompt_id uuid references prompts(id),
  recording_url text,
  transcript text,
  rubric_score jsonb,                      -- {grammar, fluency, reasoning, coherence}
  rationale text,
  recorded_at timestamptz
);

-- ============================================================
-- Campus Scheduling
-- ============================================================

create table campus_schedules (
  id uuid primary key default uuid_generate_v4(),
  program_id uuid not null references programs(id) on delete cascade,
  session_date date not null,
  capacity int not null
);

create table campus_sessions (
  application_id uuid primary key references applications(id) on delete cascade,
  schedule_id uuid not null references campus_schedules(id) on delete cascade,
  slot_time timestamptz,
  check_in_status text default 'not_checked_in',
  device_id text
);

-- ============================================================
-- Final Decision & Interview
-- ============================================================

create table final_decisions (
  application_id uuid primary key references applications(id) on delete cascade,
  decision text not null,                  -- called_for_interview, offered, rejected
  decided_by uuid references admin_users(id),
  decided_at timestamptz default now()
);

create table interviews (
  application_id uuid primary key references applications(id) on delete cascade,
  scheduled_at timestamptz,
  status text default 'pending'            -- pending, scheduled, completed, cancelled
);

create table notifications (
  id uuid primary key default uuid_generate_v4(),
  application_id uuid not null references applications(id) on delete cascade,
  channel text not null,                   -- email, whatsapp, sms
  type text not null,                      -- campus_invite, interview_invite, rejection
  sent_at timestamptz default now(),
  status text default 'sent'
);

-- ============================================================
-- INDEXES
-- ============================================================

create index idx_applications_tenant on applications(tenant_id);
create index idx_applications_program on applications(program_id);
create index idx_applications_status on applications(status);
create unique index idx_applications_program_sequence on applications(program_id, sequence_number);
create index idx_questions_bank_category on questions(bank_id, category);
create index idx_prompts_bank on prompts(bank_id);

-- ============================================================
-- ROW-LEVEL SECURITY (enable now, policies added once auth is wired up)
-- ============================================================

alter table applications enable row level security;
alter table profile_data enable row level security;
alter table uploaded_documents enable row level security;
alter table preference_match_results enable row level security;
alter table admin_decisions enable row level security;
alter table credentials enable row level security;
alter table test_a_sessions enable row level security;
alter table test_b_sessions enable row level security;
alter table final_decisions enable row level security;

-- Example policy pattern (add once admin_users JWT includes tenant_id):
-- create policy tenant_isolation on applications
--   for all using (tenant_id = current_setting('request.jwt.claims.tenant_id')::uuid);

-- ============================================================
-- SEED DATA (minimal, for local dev)
-- ============================================================

insert into tenants (name, slug) values ('Demo College', 'demo-college');

insert into programs (tenant_id, name)
  select id, 'MBA Finance' from tenants where slug = 'demo-college';

insert into preference_configs (program_id, field_name, is_hard_cutoff, cutoff_value, soft_weight)
  select id, '10th_percentage', true, 70, 0.3 from programs where name = 'MBA Finance'
  union all
  select id, '12th_percentage', true, 80, 0.3 from programs where name = 'MBA Finance'
  union all
  select id, 'certifications_count', false, null, 0.4 from programs where name = 'MBA Finance';
