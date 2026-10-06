import json
import os

import discord
from discord.ext import commands
from dotenv import load_dotenv

load_dotenv()  # читает файл .env рядом с bot.py: токен лежит там, а не в коде

token = os.getenv("DISCORD_TOKEN")
if not token:
    raise SystemExit("Нет DISCORD_TOKEN. Скопируй .env.example в .env и впиши токен.")

with open("config.json", encoding="utf-8") as f:
    cfg = json.load(f)

intents = discord.Intents.default()
intents.message_content = True  # включи и в Developer Portal (Bot -> Privileged Intents)
intents.members = True          # то же самое для Server Members Intent


class ModBot(commands.Bot):
    def __init__(self):
        super().__init__(command_prefix="!", intents=intents)
        self.cfg = cfg  # отсюда конфиг берут все коги

    async def setup_hook(self):
        await self.load_extension("cogs.moderation")
        # подсказка: глобальные слэш-команды могут появиться не сразу (до часа),
        # на время тестов быстрее синхронизировать на один сервер через tree.copy_global_to(guild=...)
        await self.tree.sync()

    async def on_ready(self):
        print(f"Вошёл как {self.user} (серверов: {len(self.guilds)})")


ModBot().run(token)
