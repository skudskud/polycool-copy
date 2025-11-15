"""
Market Categorizer Service for Data Ingestion
Uses OpenAI API to automatically categorize markets based on their question text
"""

import logging
import os
from typing import Optional

logger = logging.getLogger(__name__)

class MarketCategorizerService:
    """
    Categorizes markets using OpenAI GPT-4
    """

    # Simplified 5 categories (Oct 2025)
    CATEGORIES = [
        "Geopolitics",
        "Sports",
        "Finance",
        "Crypto",
        "Other"
    ]

    SYSTEM_PROMPT = f"""You are a market categorization assistant. Given a prediction market question, classify it into ONE of these categories:

{', '.join(CATEGORIES)}

Rules:
- Return ONLY the category name, nothing else
- "Geopolitics" is for politics, elections, international relations, wars, conflicts, government, voting, political figures, diplomatic meetings, international summits
- "Sports" includes all sports, athletes, championships, leagues, competitions, soccer, football, basketball, baseball, tennis, golf, racing
- "Finance" is for business, economy, stocks, companies, IPOs, interest rates, Fed, economic indicators, corporate news, markets, trading
- "Crypto" includes all cryptocurrency, blockchain, Bitcoin, Ethereum, NFT, DeFi, Web3, crypto prices, digital assets
- "Other" is for culture, entertainment, technology, AI, pop culture, celebrities, movies, music, art, health, science, space, education

Examples:
- "Will Trump meet with Kim Jong Un in 2025?" → Geopolitics
- "Will Erling Haaland be top scorer in Premier League 2025?" → Sports
- "Will Bitcoin reach $100,000 by December 2025?" → Crypto
- "Will Apple stock reach $200 by end of 2025?" → Finance
- "Will Oppenheimer win Best Picture at Oscars 2024?" → Other
- "Will the US Federal Reserve cut interest rates in 2025?" → Finance

If the question doesn't clearly fit any category, choose the closest match or use "Other"
"""

    def __init__(self, api_key: Optional[str] = None):
        """Initialize with OpenAI API key"""
        self.api_key = api_key or os.environ.get('OPENAI_API_KEY')
        if not self.api_key:
            logger.warning("⚠️ OPENAI_API_KEY not set - categorization disabled")
            self.enabled = False
        else:
            self.enabled = True
            logger.info("✅ Market Categorizer Service initialized")

    async def categorize_market(self, question: str, existing_category: Optional[str] = None) -> Optional[str]:
        """
        Categorize a market based on its question

        Args:
            question: The market question text
            existing_category: If provided and valid, skip categorization

        Returns:
            Category string or None if categorization fails
        """
        # If already has valid category, keep it
        if existing_category and existing_category.strip():
            # Normalize existing category if it's close to our targets
            normalized = self._normalize_category(existing_category)
            if normalized:
                return normalized

        # Skip if not enabled
        if not self.enabled:
            return None

        # Skip very short or invalid questions - default to Other
        if not question or len(question.strip()) < 10:
            return "Other"

        try:
            # Call OpenAI API (v1.0+ syntax)
            from openai import OpenAI
            client = OpenAI(api_key=self.api_key)

            response = client.chat.completions.create(
                model="gpt-4o-mini",  # Back to cheaper model but with better prompt
                messages=[
                    {"role": "system", "content": self.SYSTEM_PROMPT},
                    {"role": "user", "content": f"Categorize this prediction market: {question}"}
                ],
                temperature=0.0,  # Zero temperature for maximum consistency
                max_tokens=20  # Smaller response for mini model
            )

            category = response.choices[0].message.content.strip()

            # Clean up response - extract just the category name
            # Remove quotes, extra text, etc.
            import re
            category = re.sub(r'^["\']|["\']$', '', category)  # Remove surrounding quotes
            category = category.split('\n')[0]  # Take first line only
            category = category.strip()

            # Validate and normalize category
            if category in self.CATEGORIES:
                logger.debug(f"✅ Categorized '{question[:50]}...' as '{category}'")
                return category
            else:
                # Try to normalize invalid category to one of our 5
                normalized = self._normalize_category(category)
                if normalized:
                    logger.info(f"🔄 Normalized '{category}' → '{normalized}' for '{question[:50]}...'")
                    return normalized
                else:
                    logger.warning(f"⚠️ Could not normalize category '{category}' (raw: '{response.choices[0].message.content}') for '{question[:50]}...' - defaulting to Other")
                    return "Other"

        except Exception as e:
            logger.error(f"❌ Categorization error: {e}")
            return None

    def _normalize_category(self, category: str) -> Optional[str]:
        """
        Normalize existing category to match our 5 target categories ONLY

        Maps old/variant categories to one of: Geopolitics, Sports, Finance, Crypto, Other
        """
        cat_lower = category.lower().strip()

        # Direct matches
        if category in self.CATEGORIES:
            return category

        # Map old 7 categories to new 5 categories
        old_to_new = {
            # OLD 7 categories → NEW 5 categories
            'Politics': 'Geopolitics',
            'Trump': 'Geopolitics',
            'Elections': 'Geopolitics',
            'Business': 'Finance',
            'Geopolitics': 'Geopolitics',  # Keep as-is
            'Sports': 'Sports',  # Keep as-is
            'Crypto': 'Crypto',  # Keep as-is
        }

        # Check if it's one of the old categories
        if category in old_to_new:
            return old_to_new[category]

        # Mapping from variant categories to our 5 categories
        mappings = {
            # Geopolitics-related (Politics, Trump, Elections, International)
            'politics': 'Geopolitics',
            'trump': 'Geopolitics',
            'donald trump': 'Geopolitics',
            'elections': 'Geopolitics',
            'election': 'Geopolitics',
            'presidential election': 'Geopolitics',
            'us election': 'Geopolitics',
            'us-current-affairs': 'Geopolitics',
            'us politics': 'Geopolitics',
            'biden': 'Geopolitics',
            'global politics': 'Geopolitics',
            'world politics': 'Geopolitics',
            'russia-ukraine': 'Geopolitics',
            'china': 'Geopolitics',
            'middle east': 'Geopolitics',
            'international': 'Geopolitics',
            'government': 'Geopolitics',
            'voting': 'Geopolitics',

            # Sports-related (all sports, esports, chess)
            'nba playoffs': 'Sports',
            'nba': 'Sports',
            'nfl': 'Sports',
            'mlb': 'Sports',
            'olympics': 'Sports',
            'chess': 'Sports',
            'basketball': 'Sports',
            'football': 'Sports',
            'soccer': 'Sports',
            'esports': 'Sports',
            'counter-strike': 'Sports',
            'athletics': 'Sports',

            # Finance-related (Business, economy, stocks)
            'business': 'Finance',
            'economics': 'Finance',
            'finance': 'Finance',
            'fed': 'Finance',
            'interest rates': 'Finance',
            'stocks': 'Finance',
            'economy': 'Finance',
            'companies': 'Finance',
            'corporate': 'Finance',
            'ipo': 'Finance',

            # Crypto-related
            'nfts': 'Crypto',
            'nft': 'Crypto',
            'bitcoin': 'Crypto',
            'ethereum': 'Crypto',
            'cryptocurrency': 'Crypto',
            'blockchain': 'Crypto',
            'defi': 'Crypto',
            'web3': 'Crypto',

            # Other (culture, tech, science, entertainment)
            'coronavirus': 'Other',
            'coronavirus-': 'Other',
            'covid': 'Other',
            'health': 'Other',
            'pandemic': 'Other',
            'science': 'Other',
            'tech': 'Other',
            'technology': 'Other',
            'ai': 'Other',
            'space': 'Other',
            'pop-culture': 'Other',
            'pop culture': 'Other',
            'entertainment': 'Other',
            'celebrities': 'Other',
            'movies': 'Other',
            'music': 'Other',
            'art': 'Other',
            'culture': 'Other',
            'other': 'Other',
        }

        # Check mappings
        if cat_lower in mappings:
            return mappings[cat_lower]

        # Partial matches (in order of specificity)
        if 'trump' in cat_lower or 'election' in cat_lower or 'voting' in cat_lower or 'politic' in cat_lower:
            return 'Geopolitics'
        if 'crypto' in cat_lower or 'blockchain' in cat_lower or 'bitcoin' in cat_lower or 'ethereum' in cat_lower or 'nft' in cat_lower:
            return 'Crypto'
        if 'sport' in cat_lower or 'nba' in cat_lower or 'nfl' in cat_lower or 'soccer' in cat_lower or 'esport' in cat_lower:
            return 'Sports'
        if 'business' in cat_lower or 'financ' in cat_lower or 'econom' in cat_lower or 'stock' in cat_lower or 'company' in cat_lower:
            return 'Finance'
        if 'geopolit' in cat_lower or 'war' in cat_lower or 'international' in cat_lower or 'global' in cat_lower:
            return 'Geopolitics'

        # Default fallback: Other (covers tech, science, health, entertainment, etc.)
        return 'Other'

    def get_categories(self) -> list[str]:
        """Get list of available categories"""
        return self.CATEGORIES.copy()
