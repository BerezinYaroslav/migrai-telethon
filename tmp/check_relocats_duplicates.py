"""Read-only check whether today's Telegram signal authors are in PostgreSQL."""

import asyncio
import json
from pathlib import Path

from sqlalchemy import bindparam, text

from migrai_telethon.config import Settings
from migrai_telethon.repository import make_engine


async def main() -> None:
    scan = json.loads(
        await asyncio.to_thread(Path("var/relocats_recent_20261013.json").read_text)
    )
    ids = sorted({signal["user_id"] for chat in scan["chats"] for signal in chat["signals"]})
    engine = make_engine(Settings().database_url)
    try:
        async with engine.connect() as connection:
            statement = text(
                "SELECT telegram_user_id, best_score, signal_count, "
                "exported_at IS NOT NULL AS exported "
                "FROM candidates WHERE telegram_user_id IN :ids"
            ).bindparams(bindparam("ids", expanding=True))
            rows = (await connection.execute(statement, {"ids": ids})).all()
            print(
                json.dumps(
                    {
                        "checked": len(ids),
                        "existing": [
                            {
                                "user_id": row[0],
                                "best_score": row[1],
                                "signal_count": row[2],
                                "exported": row[3],
                            }
                            for row in rows
                        ],
                    },
                    ensure_ascii=False,
                )
            )
    finally:
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
