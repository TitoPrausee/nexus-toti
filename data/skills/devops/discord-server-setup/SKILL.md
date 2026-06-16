---
name: discord-server-setup
title: Discord Server Auto-Setup via Bot
description: Automatically create categories, channels, roles, and guide embeds on a Discord server using a discord.py bot.
---

# Discord Server Auto-Setup

Use when you need to set up a complete Discord server structure (categories, channels, roles, welcome messages) programmatically via a bot.

## Prerequisites

1. **Discord Bot Token** — Create at https://discord.com/developers/applications
   - New Application → Bot → Add Bot → Reset Token
   - **Enable ALL 3 Privileged Gateway Intents** (Presence, Server Members, Message Content)
2. **Invite the bot** to your server via OAuth2 URL Generator:
   - Scopes: `bot`, `applications.commands`
   - Permissions: `Administrator` (or: Manage Server, Manage Channels, Send Messages, Manage Messages, etc.)
3. `discord.py` installed (`pip install discord.py` or `uv pip install discord.py`)

## Server Setup Script

### 1. Roles with Specific Permissions

```python
role_perms = {
    "Admin": discord.Permissions(administrator=True),
    "Dev": discord.Permissions(
        manage_channels=True, manage_messages=True,
        kick_members=True, ban_members=True,
        create_instant_invite=True, send_messages=True,
        read_messages=True, manage_webhooks=True,
        use_application_commands=True
    ),
    "Tester": discord.Permissions(
        read_messages=True, send_messages=True,
        create_instant_invite=True, use_application_commands=True,
        read_message_history=True
    ),
    "Contributor": discord.Permissions(
        read_messages=True, send_messages=True,
        read_message_history=True, use_application_commands=True
    ),
    "Member": discord.Permissions(
        read_messages=True, send_messages=True,
        read_message_history=True
    ),
}

for role_name, perms in role_perms.items():
    existing = discord.utils.get(guild.roles, name=role_name)
    if not existing:
        await guild.create_role(
            name=role_name,
            permissions=perms,
            colour=discord.Colour.random(),
            reason="Auto-setup by bot"
        )
```

### 2. Categories & Channels Structure

```python
channel_structure = [
    ("🚀 Dev", [
        ("dev-chat", "General dev discussion"),
        ("code-reviews", "Post PRs and get code reviews"),
        ("commits-feed", "GitHub commit notifications"),
        ("modrinth-feed", "New release notifications"),
    ]),
    ("🐛 Support", [
        ("help", "Ask for help"),
        ("bug-reports", "Report bugs"),
        ("suggestions", "Feature suggestions"),
    ]),
    ("📦 Releases", [
        ("changelogs", "Release notes and changelogs"),
        ("downloads", "Downloads and installation guides"),
        ("previews", "Sneak peeks"),
    ]),
    ("🎙️ Voice", [
        ("Dev-Voice", "Voice chat"),  # Voice channel
        ("Lounge", "Hang out"),       # Text channel
    ]),
]

for category_name, channels in channel_structure:
    existing_cat = discord.utils.get(guild.categories, name=category_name)
    cat = existing_cat or await guild.create_category(category_name)
    
    for ch_name, ch_topic in channels:
        existing_ch = discord.utils.get(cat.channels, name=ch_name)
        if not existing_ch:
            is_voice = ch_name.lower().endswith("-voice") or "voice" in ch_name.lower()
            if is_voice:
                await guild.create_voice_channel(ch_name, category=cat)
            else:
                await guild.create_text_channel(ch_name, category=cat, topic=ch_topic)
```

### 3. Beautiful Guide Embeds

Use `discord.Embed()` with fields for structured guides. Best practices:

```python
embed = discord.Embed(
    title="📦 One-Click Install",
    description="Your description here",
    color=discord.Color.green()  # or Color.from_str("#CC0000")
)
embed.add_field(name="⬇️ Download", value="[Link text](url)", inline=False)
embed.add_field(name="🔧 Installation", value="Step 1\nStep 2", inline=False)
embed.set_footer(text="Footer text")
await channel.send(embed=embed)
```

**Embed tips:**
- Max **25 fields** per embed
- Use `inline=True` for 3-column layouts (name-value-name-value)
- Use `inline=False` for full-width sections
- Use `set_image(url=...)` for a banner image at the top
- Use `set_footer(text=...)` for consistent branding
- Can send multiple embeds in sequence to create sections

### 4. Important: Intents

```python
intents = discord.Intents.default()
intents.message_content = True   # Required to read messages
intents.guilds = True            # Required to see servers
intents.guild_messages = True    # Required for message events
```

## Pitfalls

- ❌ Server name is **case-sensitive and space-sensitive** — `guild.name == "TitoSpace"` not `"Tito Space"`
- ❌ If you get `PrivilegedIntentsRequired`, go to Discord Developer Portal → Bot → enable ALL 3 intents
- ❌ `TAILSCALE_SOCKET` env var doesn't work for `discord.py` (different tool)
- ❌ The bot must already be invited to the server before the script runs
- ✅ Use `guild = discord.utils.get(client.guilds, name=...)` to find the server
- ✅ Always call `await client.close()` after setup is done to end cleanly
- ✅ `asyncio.run(client.start(TOKEN))` is the correct entry point
