"""
Bridge Fees Configuration
Configuration des frais pour le bridge SOL → USDC → POL
"""

# Fee structure for bridge operations
# Frais fixes
TRANSFER_FEE_FIXED = 0.0001  # Frais fixe pour le transfert
BRIDGE_FEE_FIXED = 0.027      # Frais fixe pour le bridge (augmenté pour couvrir les frais deBridge + marge)

# Frais variables (en pourcentage)
SWAP_FEE_PERCENT = 0.0025     # 0.25% du montant swappable
BRIDGE_FEE_PERCENT = 0.0005   # 0.05% du montant bridgeable

# Note: La transaction deBridge nécessite environ 0.017 SOL de frais
# On garde 0.025 SOL pour avoir une marge de sécurité

def calculate_bridge_amounts(sol_balance: float) -> dict:
    """
    Calcule les montants pour le bridge selon la nouvelle logique de fees

    Args:
        sol_balance: Balance totale en SOL

    Returns:
        dict: Dictionnaire avec tous les montants calculés
    """

    # Vérifier que le solde est suffisant pour couvrir les frais fixes
    min_required = TRANSFER_FEE_FIXED + BRIDGE_FEE_FIXED
    if sol_balance <= min_required:
        return {
            "error": f"Balance insuffisante. Minimum requis: {min_required:.6f} SOL",
            "sol_balance": sol_balance,
            "min_required": min_required,
            "swappable_amount": 0,
            "final_amount": 0
        }

    # Étape 1: Soustraire les frais fixes
    # swappable = sol_balance - frais_fixe_transfert - frais_fixe_bridge
    swappable_amount = sol_balance - TRANSFER_FEE_FIXED - BRIDGE_FEE_FIXED

    # Étape 2: Calculer le montant final après les frais variables
    # final = swappable - (swappable * swap_fee%) - ((swappable * (1 - swap_fee%)) * bridge_fee%)
    amount_after_swap_fee = swappable_amount * (1 - SWAP_FEE_PERCENT)
    bridge_fee_variable = amount_after_swap_fee * BRIDGE_FEE_PERCENT

    final_amount = swappable_amount - (swappable_amount * SWAP_FEE_PERCENT) - bridge_fee_variable

    # Arrondir à 6 décimales (standard Solana)
    final_amount = round(final_amount, 6)

    return {
        "sol_balance": sol_balance,
        "fixed_fees": {
            "transfer": TRANSFER_FEE_FIXED,
            "bridge": BRIDGE_FEE_FIXED,
            "total": TRANSFER_FEE_FIXED + BRIDGE_FEE_FIXED
        },
        "variable_fees": {
            "swap_percent": SWAP_FEE_PERCENT,
            "bridge_percent": BRIDGE_FEE_PERCENT,
            "swap_amount": swappable_amount * SWAP_FEE_PERCENT,
            "bridge_amount": bridge_fee_variable
        },
        "swappable_amount": round(swappable_amount, 6),
        "amount_after_swap": round(amount_after_swap_fee, 6),
        "final_amount": final_amount,
        "total_fees": sol_balance - final_amount
    }

def format_fee_breakdown(fee_calc: dict) -> str:
    """
    Formate le calcul des frais pour l'affichage

    Args:
        fee_calc: Résultat de calculate_bridge_amounts

    Returns:
        str: Message formaté
    """
    if "error" in fee_calc:
        return fee_calc["error"]

    return f"""💰 **Fee Calculation:**

**Initial Balance:** {fee_calc['sol_balance']:.6f} SOL

**Fixed Fees:**
• Transfer: {fee_calc['fixed_fees']['transfer']:.6f} SOL
• Bridge: {fee_calc['fixed_fees']['bridge']:.6f} SOL
• Total Fixed: {fee_calc['fixed_fees']['total']:.6f} SOL

**Swappable Amount:** {fee_calc['swappable_amount']:.6f} SOL

**Variable Fees:**
• Swap ({fee_calc['variable_fees']['swap_percent']*100:.2f}%): {fee_calc['variable_fees']['swap_amount']:.6f} SOL
• Bridge ({fee_calc['variable_fees']['bridge_percent']*100:.2f}%): {fee_calc['variable_fees']['bridge_amount']:.6f} SOL

**Final Amount to Bridge:** {fee_calc['final_amount']:.6f} SOL
**Total Fees:** {fee_calc['total_fees']:.6f} SOL"""
