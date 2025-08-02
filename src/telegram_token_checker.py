import asyncio
import telegram

async def main():
    token = input("Пожалуйста, вставьте токен вашего Telegram-бота и нажмите Enter: ")
    print("\nПроверяю введенный токен...")
    try:
        bot = telegram.Bot(token.strip())
        bot_info = await bot.get_me()
        print(f"\n✅ Токен действителен! Имя бота: {bot_info.username}")
    except telegram.error.Unauthorized:
        print("\n❌ Ошибка: Токен недействителен (Unauthorized).")
    except Exception as e:
        print(f"\n❌ Произошла другая ошибка: {e}")

if __name__ == "__main__":
    asyncio.run(main())

