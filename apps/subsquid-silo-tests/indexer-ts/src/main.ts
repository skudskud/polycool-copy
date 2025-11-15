// Force IPv4-first DNS resolution before ANY network calls
import { setDefaultResultOrder } from 'dns'
try {
  setDefaultResultOrder('ipv4first')
  console.log('[DNS] ✅ IPv4-first DNS ordering enabled')
} catch (e) {
  console.warn('[DNS] ⚠️  Failed to set IPv4-first (Node 17+):', e)
}

// ⚠️ ADDITIONAL FIX: Disable IPv6 at Node.js level (fallback for Railway)
if (process.env.NODE_EXTRA_CA_CERTS) {
  console.log('[DNS] Using custom CA certs:', process.env.NODE_EXTRA_CA_CERTS)
}

// Force IPv4-only for Node.js DNS (more aggressive than setDefaultResultOrder)
process.env.NODE_OPTIONS = (process.env.NODE_OPTIONS || '') + ' --dns-result-order=ipv4first'
console.log('[DNS] Forced NODE_OPTIONS with ipv4first')

// Load environment variables from .env file
import 'dotenv/config'
console.log('[ENV] ✅ Environment variables loaded from .env')

import { TypeormDatabase } from '@subsquid/typeorm-store'
import { BigDecimal } from '@subsquid/big-decimal'

// Start simple HTTP healthcheck server (after other imports)
import * as http from 'http'

const HEALTH_PORT = parseInt(process.env.PORT || '3000')
const healthServer = http.createServer((req, res) => {
  if (req.method === 'GET' && (req.url === '/' || req.url === '/health' || req.url === '/health/live' || req.url === '/health/ready')) {
    res.writeHead(200, { 'Content-Type': 'application/json' })
    res.end(JSON.stringify({
      status: 'alive',
      service: 'polycool-indexer',
      timestamp: new Date().toISOString(),
      uptime: process.uptime()
    }))
  } else {
    res.writeHead(404)
    res.end('Not Found')
  }
})

healthServer.listen(HEALTH_PORT, '0.0.0.0', () => {
  console.log(`[HEALTH] ✅ Healthcheck server listening on port ${HEALTH_PORT}`)
})

import { processor, startPoolMonitoring } from './processor'
import { parseTransferEvent, parseTransferBatchEvent, extractMarketIdAndOutcome, determineTransactionType, getUserAddress } from './abi/multicall'
import { Trade, UserTransaction } from './model'
import { initWatchedAddresses, notifyNewTrades } from './webhook-notifier'
import { watchedAddressManager } from './watched-addresses'

console.log('[MAIN] Starting Subsquid indexer...')

if (!process.env.DATABASE_URL) {
  console.error('[MAIN] ❌ DATABASE_URL environment variable not set!')
  process.exit(1)
}

console.log('[MAIN] ✅ DATABASE_URL configured')
console.log('[MAIN] 🔍 Connection string:', process.env.DATABASE_URL.replace(/:[^@]*@/, ':***@'))

// ⚠️ Check RPC endpoint is configured
const rpcUrl = process.env.RPC_POLYGON_HTTP || process.env.POLYGON_RPC_URL
if (rpcUrl) {
  console.log('[MAIN] ✅ RPC Endpoint configured:', rpcUrl.substring(0, 50) + '...')
} else {
  console.warn('[MAIN] ⚠️  No RPC endpoint found (RPC_POLYGON_HTTP or POLYGON_RPC_URL)')
  console.warn('[MAIN]    Will use fallback: https://polygon-rpc.com')
}

// Parse DATABASE_URL and set individual env vars for TypeormDatabase
const connStr = process.env.DATABASE_URL
try {
  // Match: postgresql://username:password@host:port/database?query=param
  const match = connStr.match(/^postgresql:\/\/(.+?):(.+?)@(.+?):(\d+)\/(.+?)(?:\?|$)/)

  if (match) {
    let [_, username, password, host, port, database] = match

    // ⚠️ KEEP the pooler connection! It's IPv4-only by design.
    // DO NOT switch to direct db.* connection - that causes IPv6 ENETUNREACH on Railway

    console.log('[MAIN] Using Supabase Connection Pooler:', host)

    // Set env vars for TypeormDatabase (use DB_PASS not DB_PASSWORD!)
    process.env.DB_HOST = host
    process.env.DB_PORT = port
    process.env.DB_USER = username
    process.env.DB_PASS = password  // ← TypeormDatabase expects DB_PASS, not DB_PASSWORD
    process.env.DB_NAME = database

    console.log('[MAIN] Set environment variables for TypeormDatabase:')
    console.log('[MAIN]   DB_HOST:', process.env.DB_HOST)
    console.log('[MAIN]   DB_PORT:', process.env.DB_PORT)
    console.log('[MAIN]   DB_USER:', process.env.DB_USER)
    console.log('[MAIN]   DB_PASS:', process.env.DB_PASS ? '***' : 'NOT SET')
    console.log('[MAIN]   DB_NAME:', process.env.DB_NAME)

    console.log('[MAIN] Parsed connection config:')
    console.log('[MAIN]   Host:', host)
    console.log('[MAIN]   Port:', port)
    console.log('[MAIN]   Database:', database)
    console.log('[MAIN]   Username:', username)
    console.log('[MAIN]   Username format:', username?.includes('.') ? '✅ (with project ref)' : '⚠️  (without project ref)')
  } else {
    console.error('[MAIN] Failed to parse DATABASE_URL with regex')
    console.error('[MAIN] Connection string:', connStr)
    process.exit(1)
  }
} catch (e) {
  console.error('[MAIN] Failed to parse DATABASE_URL:', e)
  process.exit(1)
}

const TRANSFER_SINGLE_TOPIC = '0xc3d58168c5ae7397731d063d5bbf3d657854427343f4c083240f7aacaa2d0f62'
const TRANSFER_BATCH_TOPIC = '0x4a39dc06d4c0dbc64b70af90fd698a233a518aa5d07ce33e6397d8d63df03e93'
const USDC_TRANSFER_TOPIC = '0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef'
const USDC_ADDRESS = '0x2791bca1f2de4661ed88a30c99a7a9449aa84174'

async function main() {
  try {
    console.log('[MAIN] Initializing TypeormDatabase with explicit config...')

    // ⚠️ RAILWAY FIX: Add retry mechanism for initial Supabase connection
    // First connection can take 3-5 seconds on Railway Supabase Pooler
    let db: TypeormDatabase | null = null
    let retries = 0
    const MAX_RETRIES = 5

    while (!db && retries < MAX_RETRIES) {
      try {
        // Create TypeormDatabase ONCE - it's a singleton for the process
        db = new TypeormDatabase({
          supportHotBlocks: true,
        })
        console.log('[MAIN] TypeormDatabase created successfully')
      } catch (err: any) {
        retries++
        if (retries >= MAX_RETRIES) {
          throw err // Give up after 5 retries
        }
        const delay = Math.min(1000 * Math.pow(2, retries), 10000) // Exponential backoff: 2s, 4s, 8s, etc
        console.warn(`[MAIN] ⚠️ TypeormDatabase creation failed (attempt ${retries}/${MAX_RETRIES}):`, err.message)
        console.log(`[MAIN] Retrying in ${delay}ms...`)
        await new Promise(r => setTimeout(r, delay))
      }
    }

    if (!db) {
      throw new Error('Failed to create TypeormDatabase after ' + MAX_RETRIES + ' retries')
    }

    console.log('[MAIN] TypeormDatabase initialized, starting processor...')

    // Start pool monitoring
    startPoolMonitoring(db)

    // Initialize webhook notifier (legacy - for backwards compatibility)
    initWatchedAddresses()

    // Initialize watched addresses manager (new filtering system)
    await watchedAddressManager.init(db)
    const stats = watchedAddressManager.getStats()
    if (stats.enabled) {
      console.log(`[MAIN] 🎯 Filtering enabled: will index only ${stats.count} watched addresses`)
    } else {
      console.log(`[MAIN] ⚠️  Filtering disabled: will index ALL transactions`)
    }

    // ⚠️ processor.run() is designed to:
    // 1. Process historical blocks (backfill) from block 50M to current
    // 2. Wait for new blocks and process them
    // 3. Run indefinitely until manually stopped
    //
    // It's normal for it to slow down as it catches up to current block height
    // It's ALSO normal for it to eventually reach 100% and wait for new blocks
    //
    // DO NOT retry - let it run to completion naturally
    console.log('[MAIN] Starting processor (will process backfill then wait for new blocks)...')

    await processor.run(db, async (ctx) => {
      const transactions: UserTransaction[] = []
      // Map to store USDC amounts by transaction hash and user address
      // Structure: txHash → (userAddress → usdcAmount)
      const usdcAmounts = new Map<string, Map<string, number>>()

      // Refresh watched addresses periodically (non-blocking)
      watchedAddressManager.refresh(ctx.store).catch(err =>
        ctx.log.warn(`[WATCHED] Background refresh failed: ${err.message}`)
      )

      for (const block of ctx.blocks) {
        // block.header.timestamp is already in milliseconds
        const blockTimestamp = new Date(block.header.timestamp)

        // === PHASE 1: Accumulate ALL USDC transfers for the entire block ===
        // This ensures we have complete USDC data before processing any transfers
        for (const log of block.logs) {
          const topic0 = log.topics[0]

          // Handle USDC transfers to capture exact trade amounts
          if (topic0 === USDC_TRANSFER_TOPIC && log.address?.toLowerCase() === USDC_ADDRESS) {
            try {
              const from = ('0x' + log.topics[1].slice(26)).toLowerCase()
              const to = ('0x' + log.topics[2].slice(26)).toLowerCase()
              const amount = parseInt(log.data, 16)

              const txHash = log.transaction?.hash?.toLowerCase()
              if (!txHash) continue

              // Check if either from or to is a watched address
              const fromWatched = watchedAddressManager.isWatched(from)
              const toWatched = watchedAddressManager.isWatched(to)

              if (fromWatched || toWatched) {
                // Store USDC amount by user address with direction
                if (!usdcAmounts.has(txHash)) {
                  usdcAmounts.set(txHash, new Map())
                }

                if (fromWatched) {
                  // User is sender → USDC spent (BUY) - accumulate total and sent
                  const existing = usdcAmounts.get(txHash)!.get(from) || 0
                  usdcAmounts.get(txHash)!.set(from, existing + amount)

                  const sentKey = `sent_${from}`
                  const existingSent = usdcAmounts.get(txHash)!.get(sentKey) || 0
                  usdcAmounts.get(txHash)!.set(sentKey, existingSent + amount)

                  ctx.log.debug(`[USDC] ${from.slice(0, 10)}... spent ${amount / 1e6} USDC in tx ${txHash.slice(0, 10)}...`)
                }

                if (toWatched) {
                  // User is receiver → USDC received (SELL) - accumulate total and received
                  const existing = usdcAmounts.get(txHash)!.get(to) || 0
                  usdcAmounts.get(txHash)!.set(to, existing + amount)

                  const receivedKey = `received_${to}`
                  const existingReceived = usdcAmounts.get(txHash)!.get(receivedKey) || 0
                  usdcAmounts.get(txHash)!.set(receivedKey, existingReceived + amount)

                  ctx.log.debug(`[USDC] ${to.slice(0, 10)}... received ${amount / 1e6} USDC in tx ${txHash.slice(0, 10)}...`)
                }
              }
            } catch (err) {
              ctx.log.warn(`Failed to parse USDC transfer: ${err}`)
            }
          }
        }

        // === PHASE 2: Process TransferSingle/Batch with complete USDC data ===
        for (const log of block.logs) {
          const topic0 = log.topics[0]

          // Handle TransferSingle
          if (topic0 === TRANSFER_SINGLE_TOPIC) {
              const parsed = parseTransferEvent(log.topics, log.data)
              if (!parsed) {
                ctx.log.debug(`Failed to parse TransferSingle event at block ${block.header.height}`)
                continue
              }

              const { from, to, tokenId, amount } = parsed

              const tx = log.transaction
              if (!tx) {
                ctx.log.warn(`No transaction data for log ${log.logIndex}`)
                continue
              }

              const txId = `${tx.hash}_${log.logIndex}`

              // Extract market_id and outcome from tokenId (simple bitshift)
              const { marketId, outcome } = extractMarketIdAndOutcome(tokenId)

              // Determine transaction type based on watched addresses
              const fromWatched = watchedAddressManager.isWatched(from)
              const toWatched = watchedAddressManager.isWatched(to)

              // Skip if neither from nor to is watched
              if (!fromWatched && !toWatched) {
                continue
              }

              // First determine user address (who is trading)
              let userAddress: string

              // Check if it's a mint/burn (uses zero address)
              const isMint = from.toLowerCase() === '0x0000000000000000000000000000000000000000'
              const isBurn = to.toLowerCase() === '0x0000000000000000000000000000000000000000'

              if (isMint) {
                userAddress = to
              } else if (isBurn) {
                userAddress = from
              } else {
                // Transfer between users: determine based on which address is watched
                if (fromWatched && toWatched) {
                  // Both watched - this is unusual, log and skip
                  ctx.log.debug(`Skipping transfer between two watched addresses: ${from} -> ${to}`)
                  continue
                } else if (fromWatched) {
                  userAddress = from
                } else if (toWatched) {
                  userAddress = to
                } else {
                  continue // Neither address watched
                }
              }

              // ✅ FILTER: Skip if address not watched
              if (!watchedAddressManager.isWatched(userAddress)) {
                continue  // Don't write to DB
              }

              // Get USDC amounts and determine transaction type based on USDC flow
              const txHash = log.transaction?.hash?.toLowerCase()
              let sentUsdc = 0
              let receivedUsdc = 0
              let totalUsdcAmount = 0

              if (txHash && usdcAmounts.has(txHash)) {
                sentUsdc = usdcAmounts.get(txHash)!.get(`sent_${userAddress.toLowerCase()}`) || 0
                receivedUsdc = usdcAmounts.get(txHash)!.get(`received_${userAddress.toLowerCase()}`) || 0
                totalUsdcAmount = usdcAmounts.get(txHash)!.get(userAddress.toLowerCase()) || 0
              }

              // Determine BUY/SELL based on USDC flow direction
              let txType: 'BUY' | 'SELL'
              if (sentUsdc > 0) {
                txType = 'BUY'  // User sent USDC (bought tokens)
              } else if (receivedUsdc > 0) {
                txType = 'SELL' // User received USDC (sold tokens)
              } else {
                // No USDC movement for this user - fallback to legacy logic
                if (isMint) {
                  txType = 'BUY'
                } else if (isBurn) {
                  txType = 'SELL'
                } else {
                  // Transfer direction: sending tokens = SELL, receiving tokens = BUY
                  txType = from.toLowerCase() === userAddress.toLowerCase() ? 'SELL' : 'BUY'
                }
              }

              // Calculate price per share and total value in USDC
              let price: BigDecimal | null = null
              let amountInUsdc: BigDecimal | null = null

              if (totalUsdcAmount > 0 && txHash) {
                // totalUsdcAmount is in USDC (6 decimals), amount is in tokens (6 decimals)
                // Convert to proper decimal values
                const usdcValue = BigDecimal(totalUsdcAmount, 6) // USDC has 6 decimals
                const tokenValue = BigDecimal(amount.toString(), 6) // Polymarket tokens have 6 decimals

                // Calculate price per share: USDC value / token amount
                price = usdcValue.div(tokenValue)

                // amountInUsdc is the total USDC value for this user in this transaction
                amountInUsdc = usdcValue

                ctx.log.debug(`[PRICE] ${txType} price ${price} for ${userAddress.slice(0, 10)}... (${totalUsdcAmount / 1e6} USDC / ${Number(amount) / 1e6} shares)`)
              }

              const userTx = new UserTransaction({
                id: `${tx.hash}-${log.logIndex}`,
                txId: txId,
                userAddress: userAddress.toLowerCase(),
                positionId: tokenId.toString(),          // Store as decimal string
                marketId: marketId.toString(),           // Condition ID (hash)
                outcome: outcome,                        // 0 or 1
                txType: txType,
                amount: amount.toString(),               // Convert BigInt to String
                price: price,                            // Price per share (USDC)
                amountInUsdc: amountInUsdc,              // Total USDC value
                txHash: tx.hash,
                blockNumber: BigInt(block.header.height),
                timestamp: blockTimestamp,
              })

              transactions.push(userTx)
            }

          // Handle TransferBatch - expand each item into individual transactions
          if (topic0 === TRANSFER_BATCH_TOPIC) {
              const parsed = parseTransferBatchEvent(log.topics, log.data)
              if (!parsed) {
                ctx.log.debug(`Failed to parse TransferBatch event at block ${block.header.height}`)
                continue
              }

              const { from, to, tokenIds, amounts } = parsed
              const tx = log.transaction
              if (!tx) {
                ctx.log.warn(`No transaction data for batch log ${log.logIndex}`)
                continue
              }

              // ✅ Enrich each token in batch at indexing time
              const fromWatched = watchedAddressManager.isWatched(from)
              const toWatched = watchedAddressManager.isWatched(to)

              // Skip if neither from nor to is watched
              if (!fromWatched && !toWatched) {
                continue
              }

              // Determine if BUY or SELL based on zero address
              const isBuy = from.toLowerCase() === '0x0000000000000000000000000000000000000000'
              const isSell = to.toLowerCase() === '0x0000000000000000000000000000000000000000'

              // For transfers between users, determine direction based on watched address
              let txType: 'BUY' | 'SELL'
              let userAddress: string

              if (isBuy) {
                // Mint: tokens created for 'to' address
                txType = 'BUY'
                userAddress = to
              } else if (isSell) {
                // Burn: tokens sent to zero address from 'from'
                txType = 'SELL'
                userAddress = from
              } else {
                // Transfer between users: determine based on which address is watched
                if (fromWatched && toWatched) {
                  // Both watched - this is unusual, log and skip
                  ctx.log.debug(`Skipping batch transfer between two watched addresses: ${from} -> ${to}`)
                  continue
                } else if (fromWatched) {
                  // Watched address is sender - treat as SELL
                  txType = 'SELL'
                  userAddress = from
                } else {
                  // Watched address is receiver - treat as BUY
                  txType = 'BUY'
                  userAddress = to
                }
              }

              // ✅ FILTER: Skip if address not watched
              if (!watchedAddressManager.isWatched(userAddress)) {
                continue  // Don't write to DB
              }

              // Get USDC amount from USDC transfers, matched by user address
              const txHash = log.transaction?.hash?.toLowerCase()
              const usdcAmount = txHash && usdcAmounts.has(txHash)
                ? usdcAmounts.get(txHash)!.get(userAddress.toLowerCase())
                : undefined

              // Process each token in the batch
              for (let i = 0; i < tokenIds.length; i++) {
                const tokenId = tokenIds[i]
                const amount = amounts[i]
                const txId = `${tx.hash}_${log.logIndex}_${i}`

                // Extract market_id and outcome from tokenId
                const { marketId, outcome } = extractMarketIdAndOutcome(tokenId)

                // Calculate price per share and total value in USDC
                let price: BigDecimal | null = null
                let amountInUsdc: BigDecimal | null = null

                if (usdcAmount && txHash) {
                  // usdcAmount is in USDC (6 decimals), amount is in tokens (6 decimals)
                  // Convert to proper decimal values
                  const usdcValue = BigDecimal(usdcAmount, 6) // USDC has 6 decimals
                  const tokenValue = BigDecimal(amount.toString(), 6) // Polymarket tokens have 6 decimals

                  // Calculate price per share: USDC value / token amount
                  price = usdcValue.div(tokenValue)

                  // amountInUsdc is the total USDC value for this transaction
                  amountInUsdc = usdcValue

                  ctx.log.debug(`[PRICE] Calculated price ${price} for ${userAddress.slice(0, 10)}... (${usdcAmount / 1e6} USDC / ${Number(amount) / 1e6} shares)`)
                }

                const userTx = new UserTransaction({
                  id: `${tx.hash}-${log.logIndex}-${i}`,
                  txId: txId,
                  userAddress: userAddress.toLowerCase(),
                  positionId: tokenId.toString(),        // Store as decimal string
                  marketId: marketId.toString(),         // Condition ID (hash)
                  outcome: outcome,                      // 0 or 1
                  txType: txType,
                  amount: amount.toString(),             // Convert BigInt to String
                  price: price,                          // Price per share (USDC)
                  amountInUsdc: amountInUsdc,            // Total USDC value
                  txHash: tx.hash,
                  blockNumber: BigInt(block.header.height),
                  timestamp: blockTimestamp,
                })

                transactions.push(userTx)
              }
            }
          }
        }

        // Send webhook notifications for watched addresses (no DB write)
        if (transactions.length > 0) {
          // Log with filtering stats
          const filterStats = watchedAddressManager.getStats()
          const txsWithPrice = transactions.filter(t => t.price !== null).length

          if (filterStats.enabled) {
            ctx.log.info(
              `📤 Sending ${transactions.length} webhook notifications ` +
              `(${txsWithPrice} with price, filtering: ${filterStats.count} addresses)`
            )
          }

          // Send webhook notifications (bot will write to trades table)
          try {
            await notifyNewTrades(transactions)
          } catch (err) {
            // Non-critical: Errors logged in notifier
            ctx.log.warn(`Webhook notification error: ${err}`)
          }
        } else if (ctx.blocks.length > 0) {
          // ⚠️ DEBUG: Log when we process blocks but find no transactions
          // const blockHeights = ctx.blocks.map(b => b.header.height)
          // ctx.log.info(`[DEBUG] Processed ${ctx.blocks.length} blocks (${Math.min(...blockHeights)}-${Math.max(...blockHeights)}) with 0 transactions`)
        }
    })

    console.log('[MAIN] ✅ Processor completed (backfill finished, waiting for new blocks)')
  } catch (err) {
    console.error('[MAIN] ❌ FATAL ERROR:', err)
    process.exit(1)
  }
}

main().catch((err) => {
  console.error('[MAIN] ❌ Uncaught error in main:', err)
  process.exit(1)
})

// Graceful shutdown
process.on('SIGTERM', () => {
  console.log('[MAIN] Received SIGTERM, shutting down...')
  process.exit(0)
})

process.on('SIGINT', () => {
  console.log('[MAIN] Received SIGINT, shutting down...')
  process.exit(0)
})

process.on('uncaughtException', (err) => {
  console.error('[MAIN] Uncaught exception:', err)
  process.exit(1)
})

process.on('unhandledRejection', (reason, promise) => {
  console.error('[MAIN] Unhandled rejection at:', promise, 'reason:', reason)
  process.exit(1)
})
