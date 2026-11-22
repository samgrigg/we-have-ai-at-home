CREATE TABLE recipe_imports (
    id UUID PRIMARY KEY,
    job_id UUID NOT NULL REFERENCES jobs(id),
    conversation_id UUID NOT NULL REFERENCES conversations(id),
    created_by UUID NOT NULL REFERENCES users(id),
    source_url TEXT NOT NULL,
    title TEXT NOT NULL,
    recipe_yield TEXT NOT NULL,
    raw_ingredients JSONB NOT NULL,
    ingredients JSONB,
    multiplier NUMERIC NOT NULL DEFAULT 1,
    status TEXT NOT NULL DEFAULT 'read' CHECK (status IN ('read','draft','confirmed','dismissed')),
    confirmed_indices JSONB,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX recipe_imports_conversation ON recipe_imports(conversation_id,created_at);
