-- Add Ulysse as external leader for webhook testing
-- This will allow testing the entire copy trading flow

-- First, check if address already exists
DO $$
DECLARE
    existing_count INTEGER;
    new_virtual_id INTEGER;
BEGIN
    -- Check if address exists
    SELECT COUNT(*) INTO existing_count
    FROM external_leaders
    WHERE polygon_address = '0x...' -- REPLACE WITH YOUR ADDRESS
    ;

    IF existing_count = 0 THEN
        -- Generate virtual_id (negative number to avoid conflicts with real Telegram IDs)
        -- Use current timestamp for uniqueness
        new_virtual_id := -1 * (EXTRACT(EPOCH FROM NOW())::INTEGER);

        -- Insert new external leader
        INSERT INTO external_leaders (
            virtual_id,
            polygon_address,
            username,
            is_active,
            first_seen_at,
            last_trade_at,
            created_at,
            updated_at
        ) VALUES (
            new_virtual_id,
            '0x...', -- REPLACE WITH YOUR ADDRESS (lowercase)
            'ulysse_test',
            true,
            NOW(),
            NOW(),
            NOW(),
            NOW()
        );

        RAISE NOTICE 'Added external leader: virtual_id=%, address=0x...', new_virtual_id;
    ELSE
        RAISE NOTICE 'Address already exists in external_leaders';
    END IF;
END $$;

-- Verify insertion
SELECT
    virtual_id,
    polygon_address,
    username,
    is_active,
    created_at
FROM external_leaders
WHERE polygon_address = '0x...' -- REPLACE WITH YOUR ADDRESS
;
