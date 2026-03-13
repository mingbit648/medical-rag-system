CREATE OR REPLACE FUNCTION update_last_active_at_column()
RETURNS TRIGGER AS $$
BEGIN
    NEW.last_active_at = CURRENT_TIMESTAMP;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS update_sessions_last_active ON sessions;

CREATE TRIGGER update_sessions_last_active
    BEFORE UPDATE ON sessions
    FOR EACH ROW
    EXECUTE FUNCTION update_last_active_at_column();
