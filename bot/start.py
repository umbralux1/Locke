import asyncio
import signal

from loguru import logger

from app import dp, bot
from app.main import on_startup


def sigterm_handler(signum, frame):
    raise SystemExit


signal.signal(signal.SIGTERM, sigterm_handler)


async def main():
    try:
        asyncio.create_task(on_startup(bot))

        await dp.start_polling(
            bot,
            skip_updates=False,
        )
    except (KeyboardInterrupt, SystemExit):
        logger.error("Bot stopped!")
    finally:
        await bot.session.close()


if __name__ == "__main__":
    asyncio.run(main())
