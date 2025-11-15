"""
Leaderboard Scheduler Task
Runs every Sunday at midnight UTC to update leaderboard rankings
"""

import logging
import asyncio
from datetime import datetime, timezone
from decimal import Decimal
import pytz

from database import SessionLocal
from core.services.leaderboard_calculator import LeaderboardCalculator, DEBUG_THRESHOLD

logger = logging.getLogger(__name__)


async def calculate_and_update_leaderboard(debug_mode: bool = False):
    """
    Calculate and update both weekly and all-time leaderboards
    
    This function:
    1. Archives the previous weekly leaderboard to history
    2. Calculates new weekly leaderboard
    3. Calculates all-time leaderboard
    4. Saves both to database
    5. Notifies users of their weekly ranking
    
    Args:
        debug_mode: If True, uses $10 minimum volume. If False, uses $100
    """
    db = SessionLocal()
    try:
        logger.info("🚀 Starting leaderboard calculation...")
        
        min_volume = Decimal(str(DEBUG_THRESHOLD if debug_mode else 10))
        
        # Archive previous weekly leaderboard
        logger.info("📦 Archiving previous weekly leaderboard...")
        LeaderboardCalculator.archive_previous_weekly_leaderboard(db)
        
        # Calculate and save new weekly leaderboard
        logger.info("📊 Calculating new weekly leaderboard...")
        weekly_leaderboard = LeaderboardCalculator.calculate_weekly_leaderboard(
            db, 
            min_volume=min_volume
        )
        LeaderboardCalculator.save_leaderboard_entries(db, weekly_leaderboard)
        
        # Calculate and save all-time leaderboard
        logger.info("📊 Calculating all-time leaderboard...")
        alltime_leaderboard = LeaderboardCalculator.calculate_alltime_leaderboard(
            db,
            min_volume=min_volume
        )
        LeaderboardCalculator.save_leaderboard_entries(db, alltime_leaderboard)
        
        logger.info(f"✅ Leaderboard calculation completed!")
        logger.info(f"   Weekly: {len(weekly_leaderboard)} traders")
        logger.info(f"   All-time: {len(alltime_leaderboard)} traders")
        
        # Notify users of their weekly ranking (in background)
        asyncio.create_task(notify_users_of_ranking(db, weekly_leaderboard))
        
        return {
            'status': 'success',
            'weekly_count': len(weekly_leaderboard),
            'alltime_count': len(alltime_leaderboard),
            'timestamp': datetime.now(timezone.utc).isoformat()
        }
        
    except Exception as e:
        logger.error(f"❌ Error calculating leaderboard: {e}", exc_info=True)
        return {
            'status': 'error',
            'error': str(e),
            'timestamp': datetime.now(timezone.utc).isoformat()
        }
    
    finally:
        db.close()


async def notify_users_of_ranking(db, weekly_leaderboard: list):
    """
    Send notification to users about their weekly ranking
    Runs asynchronously to avoid blocking the scheduler
    """
    try:
        # Import telegram bot if available
        from telegram_bot import telegram_bot as global_bot
        from telegram_bot.bot import TelegramTradingBot
        
        # Get app from bot if initialized
        if global_bot and hasattr(global_bot, 'app'):
            app = global_bot.app
        else:
            logger.info("⚠️ Telegram bot not yet initialized - skipping notifications")
            return
        
        # Create a mapping of user_id -> entry for quick lookup
        user_rankings = {entry['user_id']: entry for entry in weekly_leaderboard}
        
        # Get all users from the database
        from database import User
        users = db.query(User).all()
        
        notified_count = 0
        for user in users:
            try:
                user_id = user.telegram_user_id
                entry = user_rankings.get(user_id)
                
                if entry:
                    # User is on the leaderboard
                    rank = entry['rank']
                    pnl = Decimal(str(entry['pnl_amount']))
                    pnl_pct = Decimal(str(entry['pnl_percentage']))
                    volume = Decimal(str(entry['total_volume_traded']))
                    
                    medal = get_medal_emoji(rank)
                    pnl_emoji = "📈" if pnl >= 0 else "📉"
                    pnl_symbol = "+" if pnl >= 0 else ""
                    
                    message = (
                        f"📊 <b>Weekly Leaderboard Updated!</b>\n\n"
                        f"Your Ranking: {medal} <b>#{rank}</b>\n"
                        f"P&L: {pnl_emoji} <b>{pnl_symbol}${pnl:.2f}</b> ({pnl_symbol}{pnl_pct:.2f}%)\n"
                        f"Volume: <code>${volume:.2f}</code>\n\n"
                        f"<i>Check /leaderboard to see full rankings!</i>"
                    )
                    
                    try:
                        await app.bot.send_message(
                            chat_id=user_id,
                            text=message,
                            parse_mode='HTML'
                        )
                        notified_count += 1
                    except Exception as e:
                        # Silently ignore notification errors (user may have blocked bot)
                        pass
                
            except Exception as e:
                logger.error(f"Error notifying user {user.telegram_user_id}: {e}")
                continue
        
        if notified_count > 0:
            logger.info(f"✅ Notified {notified_count} users of weekly ranking")
        
    except Exception as e:
        logger.error(f"Error in user notification: {e}")


def get_medal_emoji(rank: int) -> str:
    """Get medal emoji for rank"""
    medals = {
        1: "🥇",
        2: "🥈",
        3: "🥉",
    }
    return medals.get(rank, f"#{rank:02d}")


def schedule_leaderboard_calculation(scheduler, debug_mode: bool = False):
    """
    Schedule the leaderboard calculation to run every Sunday at midnight UTC
    
    Args:
        scheduler: APScheduler AsyncIOScheduler instance
        debug_mode: If True, runs weekly instead of on Sunday for testing
    """
    from apscheduler.triggers.cron import CronTrigger
    
    if debug_mode:
        logger.warning("🧪 DEBUG MODE: Leaderboard will run WEEKLY (every Sunday midnight UTC)")
        trigger = CronTrigger(day_of_week='sun', hour=0, minute=0, second=0, timezone='UTC')
    else:
        logger.info("✅ Production mode: Leaderboard every Sunday at midnight UTC")
        trigger = CronTrigger(day_of_week='sun', hour=0, minute=0, second=0, timezone='UTC')
    
    job = scheduler.add_job(
        calculate_and_update_leaderboard,
        trigger=trigger,
        id='leaderboard_calculation',
        name='Calculate Leaderboards',
        replace_existing=True,
        kwargs={'debug_mode': debug_mode}
    )
    
    logger.info(f"📅 Leaderboard job scheduled: {job}")
    return job


def get_next_leaderboard_run(scheduler):
    """Get the next scheduled leaderboard calculation time"""
    job = scheduler.get_job('leaderboard_calculation')
    if job:
        return job.next_run_time
    return None
