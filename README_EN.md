# Universal Discord Moderation Bot

A universal Discord bot for server moderation, suitable for any server. It protects your community with anti-spam, anti-raid, captcha verification and logs, and gives moderators handy slash commands.

Built with [discord.py](https://github.com/Rapptz/discord.py) 2.x.

## Features

- **Anti-spam**: detects flooding, mass mentions, links and repeated messages. Offenders get a timeout, and after several strikes they are kicked.
- **Anti-raid**: if too many users join in a short time, new members are temporarily kicked.
- **Captcha**: every new member gets a simple math question with buttons in DMs. Wrong answer or no answer in time means a kick.
- **Logs**: all actions are sent to a channel of your choice.
- **Slash commands**: `/clear`, `/kick`, `/ban`, `/timeout`.

Admins and members with the *Manage Messages* permission are ignored by anti-spam.

## Setup

### 1. Create the bot

1. Go to the [Discord Developer Portal](https://discord.com/developers/applications) and create an application.
2. Open the **Bot** tab and copy the token.
3. On the same tab, enable **Server Members Intent** and **Message Content Intent**.

### 2. Invite the bot

In **OAuth2 -> URL Generator** select the scopes `bot` and `applications.commands`, and the permissions:

- View Channels
- Send Messages
- Manage Messages
- Kick Members
- Ban Members
- Moderate Members

Open the generated link and add the bot to your server.

> **Important:** the bot's role must be placed **above** the roles of the members it moderates, otherwise it will not be able to kick or time them out.

### 3. Install and run

```bash
pip install -r requirements.txt
```

Copy `.env.example` to `.env` and put your token in it:

```
DISCORD_TOKEN=your_bot_token_here
```

Set `log_channel_id` in `config.json`, then start the bot:

```bash
python bot.py
```

## Configuration

All rules live in `config.json`:

| Option | Description |
| --- | --- |
| `log_channel_id` | ID of the channel where the bot writes logs |
| `antispam.max_messages` / `per_seconds` | More than this many messages in this many seconds counts as flooding |
| `antispam.max_mentions` | Maximum mentions in a single message |
| `antispam.block_links` | Delete messages with links |
| `antispam.mute_seconds` | Timeout length after a violation |
| `antispam.kick_after_strikes` | Number of violations before a kick |
| `antiraid.joins` / `per_seconds` | This many joins in this many seconds triggers raid mode |
| `antiraid.lockdown_seconds` | How long new members are kicked during raid mode |
| `captcha.enabled` | Turn the captcha on or off |
| `captcha.timeout_seconds` | Time to answer before a kick |

Every module has an `enabled` switch, so you can turn off anything you do not need.

## Slash commands

| Command | Permission | Description |
| --- | --- | --- |
| `/clear amount` | Manage Messages | Delete the last messages in a channel (1-100) |
| `/kick member [reason]` | Kick Members | Kick a member |
| `/ban member [reason]` | Ban Members | Ban a member |
| `/timeout member minutes` | Moderate Members | Time out a member (0 removes the timeout) |

## Project structure

```
bot.py              entry point, loads cogs
config.json         rule thresholds
cogs/moderation.py  anti-spam, anti-raid, captcha, commands
```

## Notes

- Strikes, captcha state and raid mode are stored in memory, so they reset when the bot restarts.
- Captcha is sent in DMs. Members with closed DMs will be kicked when the captcha times out.
- Global slash commands may take a while to appear after the first launch.

## Security

Your bot token is stored only in `.env`, which is listed in `.gitignore` and never committed. Never share your token. If it leaks, reset it in the Developer Portal right away.
