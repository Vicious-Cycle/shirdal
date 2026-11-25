import os
from shirdal import SelfBot, SQLiteStorage, TelethonAdapter

adapter = TelethonAdapter(
    os.getenv("SESSION_NAME", "my_account"),
    int(os.getenv("API_ID", "0")),
    os.getenv("API_HASH", ""),
)

bot = SelfBot(
    adapter,
    anti_flood=True,
    plugins_dir="plugins",
    hot_reload=True,
    storage=SQLiteStorage("shirdal.db"),
)

if __name__ == "__main__":
    bot.run()
