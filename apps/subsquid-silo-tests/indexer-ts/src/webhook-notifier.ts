/**
 * Webhook Notifier for Copy Trading - Send ALL trades, bot filters
 * No filtering here - the bot will check if address is watched
 */

import axios from 'axios';
import { UserTransaction } from './model';

interface WebhookPayload {
  tx_id: string;
  user_address: string;
  position_id: string;
  market_id: string | null;
  outcome: number | null;
  tx_type: string;
  amount: string;
  price: string | null;
  taking_amount: string | null; // Total USDC amount (amountInUsdc)
  tx_hash: string;
  block_number: string;
  timestamp: string;
}

/**
 * Initialize webhook system (no-op, kept for compatibility)
 */
export function initWatchedAddresses() {
  const webhookUrl = process.env.COPY_TRADING_WEBHOOK_URL;
  const webhookSecret = process.env.WEBHOOK_SECRET;

  if (webhookUrl) {
    console.log(`[WEBHOOK] ✅ Enabled - sending ALL trades to ${webhookUrl}`);
    console.log(`[WEBHOOK] 🔐 Secret configured: ${webhookSecret ? 'YES' : 'NO'}`);
  } else {
    console.log(`[WEBHOOK] ❌ Disabled - no COPY_TRADING_WEBHOOK_URL`);
  }
}

/**
 * Send webhook notification for new trade
 * Non-blocking: Errors are logged but don't stop indexing
 */
export async function notifyNewTrade(trade: UserTransaction): Promise<void> {
  const webhookUrl = process.env.COPY_TRADING_WEBHOOK_URL;
  const webhookSecret = process.env.WEBHOOK_SECRET;

  // Skip if webhooks disabled
  if (!webhookUrl) {
    return;
  }

  // ✅ NO FILTERING - Send all trades, bot will filter

  const payload: WebhookPayload = {
    tx_id: trade.txId,
    user_address: trade.userAddress,
    position_id: trade.positionId ?? '',
    market_id: trade.marketId ?? null,
    outcome: trade.outcome ?? null,
    tx_type: trade.txType,
    amount: trade.amount.toString(),
    price: trade.price?.toString() ?? null,
    taking_amount: trade.amountInUsdc?.toString() ?? null, // Total USDC spent/received
    tx_hash: trade.txHash,
    block_number: trade.blockNumber.toString(),
    timestamp: trade.timestamp.toISOString()
  };

  try {
    const startTime = Date.now();

    const headers: Record<string, string> = {
      'Content-Type': 'application/json'
    };

    if (webhookSecret) {
      headers['X-Webhook-Secret'] = webhookSecret;
    }

    await axios.post(webhookUrl, payload, {
      timeout: 15000,  // 15 second timeout (increased from 5s)
      headers
    });

    const latency = Date.now() - startTime;

    console.log(
      `[WEBHOOK] ✅ Sent for ${trade.userAddress.substring(0, 10)}... ` +
      `(${trade.txType}, ${latency}ms)`
    );

  } catch (err: any) {
    // Non-blocking error: Log and continue
    // The filter job polling will catch this trade as fallback
    console.error(
      `[WEBHOOK] ❌ Failed for ${trade.txId}: ${err.message}`,
      `(address: ${trade.userAddress.substring(0, 10)}...)`
    );
  }
}

/**
 * Batch webhook notifications (for multiple trades)
 * Sends ALL trades - bot filters based on external_leaders/smart_wallets tables
 */
export async function notifyNewTrades(trades: UserTransaction[]): Promise<void> {
  if (trades.length === 0) {
    return;
  }

  const webhookUrl = process.env.COPY_TRADING_WEBHOOK_URL;
  if (!webhookUrl) {
    return;
  }

  console.log(`[WEBHOOK] Sending ${trades.length} trade notifications...`);

  // Send ALL trades in parallel (no filtering)
  const promises = trades.map(trade => notifyNewTrade(trade));

  // Wait for all (but don't fail if some fail)
  await Promise.allSettled(promises);
}
