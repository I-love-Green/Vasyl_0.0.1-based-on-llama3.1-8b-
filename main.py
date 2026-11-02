import asyncio
from aiogram import Bot, Dispatcher
from environs import Env
from handlers.start import router as start_router
#from handlers.register import router as register_router, init_db

dp = Dispatcher()
dp.include_router(start_router)
#dp.include_router(register_router)

async def main():
    env = Env()
    env.read_env(".env")
    bot = Bot(token=env('TOKEN'))
    #init_db()
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())