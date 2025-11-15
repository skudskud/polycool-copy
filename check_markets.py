#!/usr/bin/env python3
from database import db_manager
from database import SubsquidMarketPoll
from datetime import datetime, timezone
from sqlalchemy import or_, text as sql_text

with db_manager.get_session() as db:
    now = datetime.now(timezone.utc)

    markets_query = db.query(SubsquidMarketPoll).filter(
        SubsquidMarketPoll.status == 'ACTIVE',
        SubsquidMarketPoll.accepting_orders == True,
        SubsquidMarketPoll.archived == False,
        or_(
            SubsquidMarketPoll.title.ilike('%5:00%'),
            sql_text("jsonb_path_exists(events, '$[*].event_title ? (@ like_regex \".*5:00.*\" flag \"i\")')")
        ),
        or_(
            SubsquidMarketPoll.end_date == None,
            SubsquidMarketPoll.end_date > now
        )
    ).order_by(SubsquidMarketPoll.volume.desc()).limit(10).all()

    print(f'Found {len(markets_query)} markets after SQL filters')
    for m in markets_query:
        print(f'{m.market_id}: title={m.title[:50]}..., end_date={m.end_date}, outcome_prices={m.outcome_prices}')
