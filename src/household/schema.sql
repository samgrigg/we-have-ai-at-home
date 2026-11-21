CREATE TABLE IF NOT EXISTS conversations (
    id UUID PRIMARY KEY,
    title TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS jobs (
    sequence BIGSERIAL UNIQUE,
    id UUID PRIMARY KEY,
    conversation_id UUID NOT NULL REFERENCES conversations(id),
    content TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'queued'
      CHECK (status IN ('queued', 'processing', 'completed', 'failed')),
    response TEXT,
    error TEXT,
    attempts INTEGER NOT NULL DEFAULT 0,
    input_tokens BIGINT NOT NULL DEFAULT 0,
    output_tokens BIGINT NOT NULL DEFAULT 0,
    estimated_cost_usd DOUBLE PRECISION,
    model TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE UNIQUE INDEX IF NOT EXISTS one_unfinished_job
  ON jobs(conversation_id) WHERE status <> 'completed';
CREATE INDEX IF NOT EXISTS jobs_queue ON jobs(sequence)
  WHERE status IN ('queued', 'processing');
CREATE TABLE IF NOT EXISTS shopping_items (
    name TEXT PRIMARY KEY,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS tool_receipts (
    job_id UUID NOT NULL REFERENCES jobs(id),
    call_id TEXT NOT NULL,
    tool_name TEXT NOT NULL,
    arguments JSONB NOT NULL,
    result JSONB NOT NULL,
    PRIMARY KEY (job_id, call_id)
);
