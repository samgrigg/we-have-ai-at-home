ALTER TABLE shopping_items ADD COLUMN checked BOOLEAN NOT NULL DEFAULT false;
ALTER TABLE shopping_items ADD COLUMN revision UUID NOT NULL DEFAULT gen_random_uuid();
CREATE FUNCTION rotate_grocery_revision() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    NEW.revision = gen_random_uuid();
    RETURN NEW;
END;
$$;
CREATE TRIGGER grocery_revision BEFORE UPDATE ON shopping_items
    FOR EACH ROW EXECUTE FUNCTION rotate_grocery_revision();
ALTER TABLE conversations ADD COLUMN purpose TEXT NOT NULL DEFAULT 'chat'
    CHECK (purpose IN ('chat','grocery_commands'));
ALTER TABLE conversations ADD CONSTRAINT private_grocery_commands
    CHECK (purpose <> 'grocery_commands' OR visibility = 'private');
CREATE UNIQUE INDEX one_grocery_context_per_member ON conversations(owner_user_id)
    WHERE purpose = 'grocery_commands';
