-- Editing shifts, orders waiting for a slot, frozen trial estimates and the
-- once-only confirmations that consume shift capacity.
CREATE TABLE IF NOT EXISTS shifts (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    name varchar(60) NOT NULL,
    shift_date date NOT NULL,
    capacity_hours double precision NOT NULL CHECK (capacity_hours > 0 AND capacity_hours <= 200),
    created_by varchar(100) NOT NULL REFERENCES accounts(email),
    created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (shift_date, name)
);

CREATE TABLE IF NOT EXISTS pending_orders (
    code varchar(20) PRIMARY KEY,
    title varchar(90) NOT NULL,
    deadline date NOT NULL,
    minutes double precision NOT NULL CHECK (minutes >= 0.01 AND minutes <= 180),
    shots integer NOT NULL CHECK (shots BETWEEN 1 AND 1000),
    switches integer NOT NULL CHECK (switches BETWEEN 0 AND 1000 AND switches <= shots - 1),
    created_by varchar(100) NOT NULL REFERENCES accounts(email),
    created_at timestamptz NOT NULL DEFAULT now()
);

-- A trial freezes the estimate produced by one published report.  It never
-- changes shift capacity; only a confirmation does.
CREATE TABLE IF NOT EXISTS schedule_trials (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    report_id bigint NOT NULL REFERENCES reports(id),
    report_fingerprint char(64) NOT NULL,
    model varchar(16) NOT NULL,
    created_by varchar(100) NOT NULL REFERENCES accounts(email),
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS schedule_trial_items (
    trial_id bigint NOT NULL REFERENCES schedule_trials(id) ON DELETE CASCADE,
    code varchar(20) NOT NULL,
    title varchar(90) NOT NULL,
    deadline date NOT NULL,
    hours double precision NOT NULL CHECK (hours >= 0),
    model varchar(16) NOT NULL,
    outside_range text[] NOT NULL DEFAULT '{}',
    shift_id bigint REFERENCES shifts(id),
    reason text,
    PRIMARY KEY (trial_id, code)
);

CREATE TABLE IF NOT EXISTS schedule_confirmations (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    trial_id bigint NOT NULL UNIQUE REFERENCES schedule_trials(id),
    created_by varchar(100) NOT NULL REFERENCES accounts(email),
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS schedule_confirmation_items (
    confirmation_id bigint NOT NULL REFERENCES schedule_confirmations(id) ON DELETE CASCADE,
    code varchar(20) NOT NULL,
    title varchar(90) NOT NULL,
    deadline date NOT NULL,
    shift_id bigint REFERENCES shifts(id),
    hours double precision NOT NULL CHECK (hours >= 0),
    reason text,
    recomputed boolean NOT NULL DEFAULT false,
    PRIMARY KEY (confirmation_id, code)
);

-- One order may occupy at most one confirmed shift, even across trials.
CREATE UNIQUE INDEX IF NOT EXISTS schedule_confirmation_scheduled_order
    ON schedule_confirmation_items (code) WHERE shift_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS schedule_confirmation_shift
    ON schedule_confirmation_items (shift_id) WHERE shift_id IS NOT NULL;
