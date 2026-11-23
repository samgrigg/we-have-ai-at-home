CREATE TABLE product_searches (
    id UUID PRIMARY KEY,
    item_name TEXT NOT NULL REFERENCES shopping_items(name) ON DELETE CASCADE,
    item_created_at TIMESTAMPTZ NOT NULL,
    location_id TEXT NOT NULL,
    search_term TEXT NOT NULL,
    requirement JSONB NOT NULL,
    candidates JSONB NOT NULL,
    checked_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE TABLE product_selections (
    item_name TEXT PRIMARY KEY REFERENCES shopping_items(name) ON DELETE CASCADE,
    location_id TEXT NOT NULL,
    product JSONB NOT NULL,
    packages INTEGER NOT NULL CHECK (packages BETWEEN 1 AND 99),
    checked_at TIMESTAMPTZ NOT NULL,
    selected_by UUID NOT NULL REFERENCES users(id),
    selected_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE TABLE product_preferences (
    search_term TEXT NOT NULL,
    location_id TEXT NOT NULL,
    product_id TEXT NOT NULL,
    updated_by UUID NOT NULL REFERENCES users(id),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (search_term,location_id)
);
