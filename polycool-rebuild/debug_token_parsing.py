import json

# Simuler les données de la DB
clob_token_ids_raw = "[\"114304586861386186441621124384163963092522056897081085884483958561365015034812\", \"112744882674787019048577842008042029962234998947364561417955402912669471494485\"]"
outcomes = ['Yes', 'No']
position_outcome = 'No'

print(f"🔍 DEBUG - Market data: outcomes={outcomes}, position.outcome={position_outcome}")
print(f"🔍 DEBUG - clob_token_ids_raw: {clob_token_ids_raw}")

try:
    print(f"🔍 STEP 1 - Raw: {clob_token_ids_raw} (type: {type(clob_token_ids_raw)})")

    # First parse
    first_parse = json.loads(clob_token_ids_raw) if isinstance(clob_token_ids_raw, str) else clob_token_ids_raw
    print(f"🔍 STEP 2 - After first json.loads: {first_parse} (type: {type(first_parse)})")

    # Second parse if needed
    clob_token_ids = json.loads(first_parse) if isinstance(first_parse, str) else first_parse
    print(f"🔍 STEP 3 - After second json.loads: {clob_token_ids} (type: {type(clob_token_ids)})")

    if isinstance(clob_token_ids, list):
        print(f"🔍 STEP 4 - It's a list with {len(clob_token_ids)} items")
    outcome_index = outcomes.index(position_outcome) if position_outcome in outcomes else 0
        print(f"🔍 STEP 5 - outcome_index: {outcome_index}")

        if outcome_index < len(clob_token_ids):
            token_id = clob_token_ids[outcome_index]
            print(f"🔍 STEP 6 - token_id at index {outcome_index}: {token_id}")
        else:
            token_id = None
            print(f"🔍 ERROR - outcome_index {outcome_index} >= list length {len(clob_token_ids)}")
    else:
        token_id = None
        print(f"🔍 ERROR - Not a list after parsing!")

except Exception as e:
    print(f"❌ Error: {e}")

# Vérifier avec l'API Polymarket
print("\n🔍 Comparaison avec API Polymarket:")
print("API Polymarket asset:", "112744882674787019048577842008042029962234998947364561417955402912669471494485")
print("Notre token_id parsé:", token_id)
print("Match:", "112744882674787019048577842008042029962234998947364561417955402912669471494485" == token_id)
