import { Pool } from 'pg'
import * as dotenv from 'dotenv'
import fetch from 'node-fetch'

dotenv.config()

const db = new Pool({
  connectionString: process.env.DATABASE_URL || 'postgresql://localhost:5432/postgres',
  ssl: true,
  idleTimeoutMillis: 30000,
  connectionTimeoutMillis: 5000,
})

async function enrichPrices() {
  try {
    // FIRST: Try to enrich with local poller data (fast)
    const localQuery = `
      UPDATE subsquid_user_transactions_v2
      SET price = (
        SELECT last_mid
        FROM subsquid_markets_poll
        WHERE subsquid_markets_poll.condition_id = CONCAT('0x', subsquid_user_transactions_v2.market_id)
      )
      WHERE price IS NULL
      AND market_id IS NOT NULL
      RETURNING tx_id
    `

    const localResult = await db.query(localQuery)
    const localEnrichedCount = localResult.rowCount || 0

    console.log(`[${new Date().toISOString()}] ✓ Enriched ${localEnrichedCount} transactions with local poller data`)

    // SECOND: For remaining NULL prices, try to fetch from Polymarket API
    const remainingQuery = `
      SELECT DISTINCT market_id
      FROM subsquid_user_transactions_v2
      WHERE price IS NULL
      AND market_id IS NOT NULL
      LIMIT 10
    `

    const remainingResult = await db.query(remainingQuery)

    if (remainingResult.rows.length > 0) {
      console.log(`[${new Date().toISOString()}] → Fetching ${remainingResult.rows.length} missing market prices from API...`)

      let apiEnrichedCount = 0

      for (const row of remainingResult.rows) {
        const conditionId = row.market_id

        try {
          // Try to get market data from Polymarket API
          const marketResponse = await fetch(`https://gamma-api.polymarket.com/markets/${conditionId}`)
          if (marketResponse.ok) {
            const marketData = await marketResponse.json() as any
            const outcomePrices = marketData.outcomePrices

            if (outcomePrices && outcomePrices.length >= 2) {
              // Use mid price as fallback
              const midPrice = (parseFloat(outcomePrices[0]) + parseFloat(outcomePrices[1])) / 2

              // Update transactions for this market
              const updateQuery = `
                UPDATE subsquid_user_transactions_v2
                SET price = $1
                WHERE market_id = $2
                AND price IS NULL
              `
              const updateResult = await db.query(updateQuery, [midPrice.toString(), conditionId])
              apiEnrichedCount += updateResult.rowCount || 0

              console.log(`[${new Date().toISOString()}] ✓ Enriched market ${conditionId}: ${midPrice}`)
            }
          }
        } catch (apiErr: any) {
          console.warn(`[${new Date().toISOString()}] ⚠️ Failed to fetch price for market ${conditionId}:`, apiErr.message)
        }

        // Rate limiting
        await new Promise(resolve => setTimeout(resolve, 100))
      }

      console.log(`[${new Date().toISOString()}] ✓ Enriched ${apiEnrichedCount} transactions with API data`)
    }

    if (localEnrichedCount === 0 && remainingResult.rows.length === 0) {
      console.log(`[${new Date().toISOString()}] → No transactions to enrich`)
    }
  } catch (err) {
    console.error(`[${new Date().toISOString()}] ✗ Error enriching prices:`, err)
  }
}

// Run immediately on start
enrichPrices()

// Run every 60 seconds
setInterval(enrichPrices, 60_000)

console.log('[ENRICH] Price enrichment job started (runs every 60s)')

// Graceful shutdown
process.on('SIGTERM', async () => {
  console.log('[ENRICH] Received SIGTERM, shutting down...')
  await db.end()
  process.exit(0)
})
