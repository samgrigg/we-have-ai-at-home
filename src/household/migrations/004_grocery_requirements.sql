-- Preserve display text and existing item keys while persisting parsed requirements.
ALTER TABLE shopping_items ADD COLUMN requirement JSONB;
