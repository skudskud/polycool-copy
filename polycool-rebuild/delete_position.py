import asyncio
import os
os.environ['DATABASE_URL'] = 'postgresql+psycopg://postgres.xxzdlbwfyetaxcmodiec:ClDSK0N5IedorZes@aws-1-eu-north-1.pooler.supabase.com:6543/postgres'

from core.database.connection import get_db
from core.database.models import Position
from sqlalchemy import delete

async def delete_position():
    position_id = 4

    async with get_db() as db:
        # Vérifier que la position existe avant de la supprimer
        result = await db.execute(
            Position.__table__.select().where(Position.id == position_id)
        )
        position = result.fetchone()

        if position:
            print(f"🗑️ Trouvé position ID {position_id}: {dict(position)}")

            # Supprimer la position
            await db.execute(
                delete(Position).where(Position.id == position_id)
            )
            await db.commit()

            print(f"✅ Position ID {position_id} supprimée avec succès")

            # Vérifier que la suppression a fonctionné
            result = await db.execute(
                Position.__table__.select().where(Position.id == position_id)
            )
            remaining = result.fetchone()

            if remaining:
                print("❌ Erreur: La position existe encore")
            else:
                print("✅ Vérification: Position supprimée définitivement")
        else:
            print(f"❌ Position ID {position_id} non trouvée")

asyncio.run(delete_position())
