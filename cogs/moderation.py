import asyncio
import random
import re
import time
from collections import defaultdict, deque
from datetime import timedelta

import discord
from discord import app_commands
from discord.ext import commands

LINK_RE = re.compile(r"(https?://|www\.|discord\.gg/)", re.I)
MAX_TIMEOUT = timedelta(days=27)  # у Discord потолок таймаута 28 дней


class CaptchaView(discord.ui.View):
    """Кнопки с вариантами ответа. Шлём в ЛС: участник в таймауте не может
    писать на сервере, а в личке с ботом - может."""

    def __init__(self, cog, member, right, options):
        super().__init__(timeout=None)
        self.cog = cog
        self.member = member
        self.right = right
        for opt in options:
            btn = discord.ui.Button(label=str(opt), style=discord.ButtonStyle.primary)
            btn.callback = self._make_cb(opt)
            self.add_item(btn)

    def _make_cb(self, opt):
        # замыкание нужно, чтобы каждая кнопка помнила своё число
        async def cb(interaction: discord.Interaction):
            await interaction.response.edit_message(content="Ответ принят.", view=None)
            await self.cog.finish_captcha(self.member, opt == self.right)
        return cb


class Moderation(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.cfg = bot.cfg

        # всё хранится в памяти: после перезапуска страйки и рейд-режим сбросятся.
        # Если нужно сохранять - добавь sqlite
        self.recent = defaultdict(lambda: deque(maxlen=20))  # (guild, user) -> [(время, текст)]
        self.strikes = defaultdict(int)                      # (guild, user) -> нарушения
        self.joins = defaultdict(deque)                      # guild -> времена входов
        self.lockdown_until = {}                             # guild -> время конца рейд-режима
        self.pending = {}                                    # (guild, user) -> задача таймаута капчи

    async def log(self, guild, text):
        # подсказка: id канала один на весь бот, поэтому он подойдёт только для одного сервера
        channel = guild.get_channel(self.cfg["log_channel_id"])
        if channel:
            try:
                await channel.send(text)
            except discord.Forbidden:
                pass

    # ---------- антиспам ----------

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        cfg = self.cfg["antispam"]
        if not cfg["enabled"] or message.author.bot or not message.guild:
            return

        # админов и модераторов не трогаем
        perms = message.author.guild_permissions
        if perms.administrator or perms.manage_messages:
            return

        key = (message.guild.id, message.author.id)
        now = time.time()
        hist = self.recent[key]
        hist.append((now, message.content))

        burst = [t for t, _ in hist if now - t <= cfg["per_seconds"]]
        same = [1 for t, txt in hist if txt == message.content and now - t <= 60]
        mentions = len(message.mentions) + len(message.role_mentions)

        reason = None
        if len(burst) > cfg["max_messages"]:
            reason = "флуд"
        elif mentions > cfg["max_mentions"]:
            reason = "массовые упоминания"
        elif cfg["block_links"] and LINK_RE.search(message.content):
            reason = "ссылка"
        elif len(same) >= 3:
            reason = "повторы одного текста"

        if reason:
            await self.punish(message, reason)

    async def punish(self, message: discord.Message, reason: str):
        cfg = self.cfg["antispam"]
        member = message.author
        key = (message.guild.id, member.id)

        self.strikes[key] += 1
        n = self.strikes[key]

        try:
            await message.delete()
        except discord.HTTPException:
            pass  # уже удалено

        try:
            if n >= cfg["kick_after_strikes"]:
                await member.kick(reason=f"антиспам: {reason}")
                self.strikes.pop(key, None)
                action = "кик"
            else:
                await member.timeout(timedelta(seconds=cfg["mute_seconds"]),
                                     reason=f"антиспам: {reason}")
                action = f"таймаут на {cfg['mute_seconds']} сек"
        except discord.Forbidden:
            # частая ошибка: роль бота стоит ниже роли участника
            action = "не хватило прав (подними роль бота выше)"

        await self.log(message.guild,
                       f"[антиспам] {member}: {reason} -> {action} (страйк {n})")

    # ---------- антирейд и капча ----------

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member):
        if member.bot:
            return

        guild = member.guild
        raid = self.cfg["antiraid"]
        now = time.time()

        if raid["enabled"]:
            q = self.joins[guild.id]
            q.append(now)
            while q and now - q[0] > raid["per_seconds"]:
                q.popleft()

            # порог пробит - включаем рейд-режим
            if len(q) >= raid["joins"] and now > self.lockdown_until.get(guild.id, 0):
                self.lockdown_until[guild.id] = now + raid["lockdown_seconds"]
                await self.log(guild, f"[антирейд] {len(q)} входов за {raid['per_seconds']} сек, "
                                      f"новички кикаются {raid['lockdown_seconds']} сек")

            if self.lockdown_until.get(guild.id, 0) > now:
                try:
                    await member.kick(reason="антирейд")
                except discord.HTTPException:
                    pass
                await self.log(guild, f"[антирейд] кик {member}")
                return

        if self.cfg["captcha"]["enabled"]:
            await self.start_captcha(member)

    @commands.Cog.listener()
    async def on_member_remove(self, member: discord.Member):
        # ушёл сам, не дождавшись капчи - задача таймаута больше не нужна
        task = self.pending.pop((member.guild.id, member.id), None)
        if task:
            task.cancel()

    async def start_captcha(self, member: discord.Member):
        a, b = random.randint(2, 9), random.randint(2, 9)
        right = a + b

        options = {right}
        while len(options) < 4:
            options.add(random.randint(4, 18))
        options = random.sample(sorted(options), 4)  # перемешали

        try:
            await member.timeout(MAX_TIMEOUT, reason="капча")
        except discord.Forbidden:
            await self.log(member.guild, "[капча] не смог выдать таймаут: проверь права и роль бота")
            return

        key = (member.guild.id, member.id)
        self.pending[key] = asyncio.create_task(self._captcha_timeout(member))

        try:
            await member.send(f"Капча для **{member.guild.name}**. Сколько будет {a} + {b}?",
                              view=CaptchaView(self, member, right, options))
        except discord.Forbidden:
            await self.log(member.guild, f"[капча] у {member} закрыты ЛС, он будет кикнут по таймауту")

    async def _captcha_timeout(self, member: discord.Member):
        await asyncio.sleep(self.cfg["captcha"]["timeout_seconds"])
        # если задача дошла сюда и ещё в pending, значит ответа не было
        if self.pending.pop((member.guild.id, member.id), None):
            try:
                await member.kick(reason="не прошёл капчу вовремя")
            except discord.HTTPException:
                pass
            await self.log(member.guild, f"[капча] {member} не ответил вовремя -> кик")

    async def finish_captcha(self, member: discord.Member, ok: bool):
        task = self.pending.pop((member.guild.id, member.id), None)
        if task is None:
            return  # капча уже закрыта
        task.cancel()

        try:
            if ok:
                await member.timeout(None)
                await self.log(member.guild, f"[капча] {member} прошёл проверку")
            else:
                await member.kick(reason="ошибка в капче")
                await self.log(member.guild, f"[капча] {member} ошибся -> кик")
        except discord.HTTPException:
            pass

    # ---------- слэш-команды ----------
    # default_permissions скрывает команду от тех, у кого нет права;
    # админ сервера может перенастроить это в Параметры -> Интеграции

    @app_commands.command(name="clear", description="Удалить последние сообщения в канале")
    @app_commands.default_permissions(manage_messages=True)
    @app_commands.guild_only()
    async def clear(self, interaction: discord.Interaction,
                    amount: app_commands.Range[int, 1, 100]):
        await interaction.response.defer(ephemeral=True)  # purge может идти дольше 3 секунд
        deleted = await interaction.channel.purge(limit=amount)
        await interaction.followup.send(f"Удалено сообщений: {len(deleted)}", ephemeral=True)
        await self.log(interaction.guild,
                       f"[команда] {interaction.user} удалил {len(deleted)} сообщ. в #{interaction.channel}")

    @app_commands.command(name="kick", description="Выгнать участника")
    @app_commands.default_permissions(kick_members=True)
    @app_commands.guild_only()
    async def kick(self, interaction: discord.Interaction, member: discord.Member,
                   reason: str = "не указана"):
        try:
            await member.kick(reason=reason)
        except discord.Forbidden:
            return await interaction.response.send_message(
                "Не могу: у участника роль выше моей или нет права.", ephemeral=True)
        await interaction.response.send_message(f"{member} выгнан.", ephemeral=True)
        await self.log(interaction.guild, f"[команда] {interaction.user} кикнул {member}: {reason}")

    @app_commands.command(name="ban", description="Забанить участника")
    @app_commands.default_permissions(ban_members=True)
    @app_commands.guild_only()
    async def ban(self, interaction: discord.Interaction, member: discord.Member,
                  reason: str = "не указана"):
        try:
            await member.ban(reason=reason)
        except discord.Forbidden:
            return await interaction.response.send_message(
                "Не могу: у участника роль выше моей или нет права.", ephemeral=True)
        await interaction.response.send_message(f"{member} забанен.", ephemeral=True)
        await self.log(interaction.guild, f"[команда] {interaction.user} забанил {member}: {reason}")

    @app_commands.command(name="timeout", description="Выдать таймаут (0 минут = снять)")
    @app_commands.default_permissions(moderate_members=True)
    @app_commands.guild_only()
    async def timeout(self, interaction: discord.Interaction, member: discord.Member,
                      minutes: app_commands.Range[int, 0, 40320]):
        try:
            await member.timeout(timedelta(minutes=minutes) if minutes else None)
        except discord.Forbidden:
            return await interaction.response.send_message(
                "Не могу: у участника роль выше моей или нет права.", ephemeral=True)
        text = f"таймаут {minutes} мин" if minutes else "таймаут снят"
        await interaction.response.send_message(f"{member}: {text}.", ephemeral=True)
        await self.log(interaction.guild, f"[команда] {interaction.user} -> {member}: {text}")


async def setup(bot):
    await bot.add_cog(Moderation(bot))
