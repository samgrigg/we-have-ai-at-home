DO $$ BEGIN
    IF EXISTS (SELECT 1 FROM jobs WHERE status IN ('queued','processing','failed')) THEN
        RAISE EXCEPTION 'Resolve unfinished POC jobs before the family-accounts migration';
    END IF;
END $$;
CREATE TABLE users (
    id UUID PRIMARY KEY,
    google_subject TEXT UNIQUE NOT NULL,
    email TEXT UNIQUE NOT NULL,
    display_name TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE TABLE sessions (
    token_hash TEXT PRIMARY KEY,
    user_id UUID NOT NULL REFERENCES users(id),
    expires_at TIMESTAMPTZ NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX sessions_expiry ON sessions(expires_at);
ALTER TABLE jobs DROP CONSTRAINT jobs_status_check;
ALTER TABLE jobs ADD CONSTRAINT jobs_status_check
    CHECK (status IN ('queued','processing','completed','failed','cancelled'));
DROP INDEX one_unfinished_job;
CREATE UNIQUE INDEX one_unfinished_job ON jobs(conversation_id)
    WHERE status NOT IN ('completed','cancelled');
ALTER TABLE conversations ADD COLUMN visibility TEXT NOT NULL DEFAULT 'legacy_shared'
    CHECK (visibility IN ('private','family','legacy_shared'));
ALTER TABLE conversations ADD COLUMN owner_user_id UUID REFERENCES users(id);
ALTER TABLE conversations ADD CONSTRAINT conversation_ownership CHECK (
    (visibility = 'private' AND owner_user_id IS NOT NULL) OR
    (visibility <> 'private' AND owner_user_id IS NULL)
);
CREATE UNIQUE INDEX one_family_chat ON conversations(visibility) WHERE visibility='family';
ALTER TABLE jobs ADD COLUMN submitted_by UUID REFERENCES users(id);
ALTER TABLE shopping_items ADD COLUMN added_by UUID REFERENCES users(id);
-- The household approved discarding this POC list. This migration runs once.
DELETE FROM shopping_items;
INSERT INTO conversations(id,title,visibility)
VALUES ('00000000-0000-4000-8000-000000000001','Family chat','family');
