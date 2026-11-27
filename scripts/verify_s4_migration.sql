DO $$
BEGIN
    IF EXISTS (
        SELECT FROM information_schema.columns WHERE table_schema = 'gamification'
        AND table_name = 'visits' AND column_name IN ('user_latitude', 'user_longitude')
    ) OR NOT EXISTS (
        SELECT FROM gamification.visits WHERE id = 'visit-s2' AND distance_m = 0 AND accuracy_m IS NULL
    ) THEN
        RAISE EXCEPTION 'Legacy visit result was lost or raw GPS remains';
    END IF;
    IF NOT EXISTS (
        SELECT FROM gamification.route_completions WHERE id = 'enrollment-s2'
        AND route_id = 'route-s2' AND reward_amount = 0
    ) OR EXISTS (SELECT FROM benefits.ledger) OR to_regclass('benefits.wallets') IS NULL THEN
        RAISE EXCEPTION 'Legacy completion or wallet migration is inconsistent';
    END IF;
    IF NOT EXISTS (
        SELECT FROM catalog.routes WHERE id = 'route-s2' AND NOT is_active
        AND NOT is_removed AND reward_amount = 0
    ) THEN
        RAISE EXCEPTION 'Legacy route with insufficient points should require review';
    END IF;
END $$;
