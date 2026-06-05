"""
Nexus Contributor Bot — Discord + GitHub Integration

Listens for `!apply <github-username>` in #contributor-onboarding,
verifies the GitHub account, grants Discord role, adds repo collaborator,
creates a contrib branch, and sends a welcome message.

Run as: python3 nexus/contributor_bot.py
"""

import os
import re
import json
import time
import asyncio
import urllib.request
import urllib.error
from pathlib import Path

import discord
from discord.ext import commands

# --- Config ---
DISCORD_TOKEN = os.environ.get("DISCORD_BOT_TOKEN") or open(
    "/opt/data/home/.fitspar-discord-token"
).read().strip()

# GitHub token from git credentials or env
def get_github_token() -> str:
    """Extract GitHub token from multiple sources."""
    # Method 1: Environment variable
    token = os.environ.get("GITHUB_TOKEN")
    if token and token != "***" and len(token) > 10:
        return token

    # Method 2: hosts.yml (most reliable)
    hosts_yml = Path.home() / ".config/gh/hosts.yml"
    if hosts_yml.exists():
        content = hosts_yml.read_text()
        match = re.search(r"oauth_token:\s*(\S+)", content)
        if match:
            return match.group(1)

    # Method 3: .git-credentials
    git_creds = Path.home() / ".git-credentials"
    if git_creds.exists():
        for line in git_creds.read_text().splitlines():
            if "github.com" in line:
                match = re.search(r"://[^:]+:([^@]+)@", line)
                if match:
                    return match.group(1)

    # Method 4: git credential fill
    import subprocess
    proc = subprocess.run(
        ["git", "credential", "fill"],
        input=b"protocol=https\nhost=github.com\n",
        capture_output=True,
        timeout=10,
        cwd="/opt/data/home/nexus-toti",
    )
    for line in proc.stdout.decode().split("\n"):
        if line.startswith("password="):
            return line.split("=", 1)[1].strip()

    raise RuntimeError("No GitHub token found")


GITHUB_TOKEN = None  # Lazy loaded
GITHUB_REPO = "TitoPrausee/nexus-toti"  # owner/repo
GITHUB_API = "https://api.github.com"

# Discord IDs
GUILD_ID = 1502435004788244490  # TitoSpace
ONBOARDING_CH = 1512389338070122577  # #contributor-onboarding
VERIFIED_CH = 1512389349000614012  # #contributor-verified
CHAT_CH = 1512389343975833740  # #contributor-chat
NEXUS_ROLE_ID = 1512389334110830663  # Nexus Contributor role


# --- GitHub API ---
def github_api(method: str, path: str, data: dict = None) -> dict | None:
    """Make GitHub API call."""
    global GITHUB_TOKEN
    if GITHUB_TOKEN is None:
        GITHUB_TOKEN = get_github_token()

    url = f"{GITHUB_API}{path}"
    headers = {
        "Authorization": f"Bearer {GITHUB_TOKEN}",
        "Accept": "application/vnd.github.v3+json",
        "User-Agent": "NexusContributorBot/1.0",
    }
    if data:
        req = urllib.request.Request(
            url, headers=headers, method=method, data=json.dumps(data).encode()
        )
    else:
        req = urllib.request.Request(url, headers=headers, method=method)
    try:
        resp = urllib.request.urlopen(req, timeout=15)
        if resp.status == 204:
            return None
        return json.loads(resp.read())
    except urllib.error.HTTPError as e:
        body = e.read().decode()[:300]
        print(f"GitHub API error {e.code}: {body}")
        return {"error": e.code, "body": body}
    except Exception as e:
        print(f"GitHub API exception: {e}")
        return {"error": str(e)}


def verify_github_user(username: str) -> dict | None:
    """Verify a GitHub user exists and get their info."""
    result = github_api("GET", f"/users/{username}")
    if result and "error" not in result:
        return result
    return None


def add_collaborator(username: str) -> bool:
    """Add user as collaborator to the nexus-toti repo."""
    result = github_api(
        "PUT",
        f"/repos/{GITHUB_REPO}/collaborators/{username}",
        {"permission": "write"},
    )
    if result and "error" not in result:
        return True
    # 201 = invited, 204 = already collaborator
    return result is not None


def create_contrib_branch(username: str) -> bool:
    """Create a contrib/<username> branch from main."""
    # Get main branch SHA
    main_ref = github_api("GET", f"/repos/{GITHUB_REPO}/git/ref/heads/main")
    if not main_ref or "error" in main_ref or "object" not in main_ref:
        print(f"Could not get main ref: {main_ref}")
        return False

    sha = main_ref["object"]["sha"]
    branch_name = f"contrib/{username}"

    result = github_api(
        "POST",
        f"/repos/{GITHUB_REPO}/git/refs",
        {"ref": f"refs/heads/{branch_name}", "sha": sha},
    )
    if result and "error" not in result:
        return True
    # 422 = branch already exists
    if result and result.get("error") == 422:
        print(f"Branch {branch_name} already exists")
        return True
    return False


# --- Discord Bot ---
intents = discord.Intents.default()
intents.message_content = True
intents.guilds = True
intents.members = True

bot = commands.Bot(command_prefix="!", intents=intents)


@bot.event
async def on_ready():
    print(f"Nexus Contributor Bot online as {bot.user}")
    print(f"Watching #{bot.get_channel(ONBOARDING_CH)} for !apply commands")


@bot.command(name="apply")
async def apply_command(ctx, github_username: str = None):
    """Apply as a Nexus contributor. Usage: !apply <github-username>"""

    # Only work in #contributor-onboarding
    if ctx.channel.id != ONBOARDING_CH:
        await ctx.send(
            f"Bitte nutze <#{ONBOARDING_CH}> fuer die Anmeldung!",
            delete_after=10,
        )
        return

    if not github_username:
        await ctx.send(
            "Bitte gib deinen GitHub Username an!\n"
            "Beispiel: `!apply octocat`",
            delete_after=15,
        )
        return

    # Sanitize username
    github_username = github_username.strip().lstrip("@")
    if not re.match(r"^[a-zA-Z0-9](?:[a-zA-Z0-9]|-(?=[a-zA-Z0-9])){0,38}$", github_username):
        await ctx.send("Ungueltiger GitHub Username.")
        return

    discord_user = ctx.author
    await ctx.send(
        f"Pruefe `{github_username}` auf GitHub...",
    )

    # Step 1: Verify GitHub user exists
    gh_user = verify_github_user(github_username)
    if not gh_user:
        await ctx.send(
            f"GitHub User `{github_username}` nicht gefunden. "
            "Bitte pruefe den Username und versuche es erneut."
        )
        return

    gh_name = gh_user.get("name") or github_username
    gh_avatar = gh_user.get("avatar_url", "")
    gh_bio = gh_user.get("bio", "Keine Bio") or "Keine Bio"
    gh_public_repos = gh_user.get("public_repos", 0)
    gh_created = gh_user.get("created_at", "unbekannt")[:10]

    # Step 2: Add as collaborator
    collab_result = add_collaborator(github_username)
    collab_status = "Einladung gesendet" if collab_result else "Fehler"

    # Step 3: Create contrib branch
    branch_result = create_contrib_branch(github_username)

    # Step 4: Assign Discord role
    guild = ctx.guild
    role = guild.get_role(NEXUS_ROLE_ID)
    if role and role not in discord_user.roles:
        await discord_user.add_roles(role)
        role_status = "Rolle vergeben"
    else:
        role_status = "Rolle bereits vorhanden"

    # Step 5: Send success embed in onboarding
    embed = discord.Embed(
        title="Verifizierung erfolgreich!",
        description=f"Willkommen, **{gh_name}**! Du bist jetzt Nexus Contributor.",
        color=0x5865F2,
    )
    embed.set_thumbnail(url=gh_avatar)
    embed.add_field(name="GitHub", value=f"[{github_username}](https://github.com/{github_username})", inline=True)
    embed.add_field(name="Oeffentliche Repos", value=str(gh_public_repos), inline=True)
    embed.add_field(name="Repo-Access", value=collab_status, inline=True)
    embed.add_field(name="Branch", value=f"`contrib/{github_username}` {'erstellt' if branch_result else 'fehler'}", inline=True)
    embed.add_field(name="Discord-Rolle", value=role_status, inline=True)
    embed.add_field(
        name="Naechste Schritte",
        value=f"1. Akzeptiere die Einladung auf GitHub\n"
              f"2. Clone: `git clone https://github.com/{GITHUB_REPO}`\n"
              f"3. Branch: `git checkout contrib/{github_username}`\n"
              f"4. Code, commit, push, PR!",
        inline=False,
    )
    embed.set_footer(text="NEXUS v7 | Open Source AI Agent")
    await ctx.send(embed=embed)

    # Step 6: Welcome message in #contributor-verified
    verified_ch = bot.get_channel(VERIFIED_CH)
    if verified_ch:
        await verified_ch.send(
            f"Willkommen <@{discord_user.id}> ({github_username}) als Nexus Contributor! "
            f"Deine Branch: `contrib/{github_username}` — viel Erfolg!",
        )


@bot.command(name="status")
async def status_command(ctx, github_username: str = None):
    """Check your contributor status. Usage: !status [github-username]"""
    if ctx.channel.id != ONBOARDING_CH:
        return

    username = github_username or ctx.author.name
    gh_user = verify_github_user(username.strip().lstrip("@"))
    if not gh_user:
        await ctx.send(f"GitHub User `{username}` nicht gefunden.")
        return

    # Check if they're a collaborator
    collab = github_api("GET", f"/repos/{GITHUB_REPO}/collaborators/{username}")
    is_collab = collab and "error" not in collab

    await ctx.send(
        f"Status fuer `{username}`:\n"
        f"- GitHub: {gh_user.get('name', username)}\n"
        f"- Collaborator: {'Ja' if is_collab else 'Nein'}\n"
        f"- Link: https://github.com/{username}",
    )


@bot.command(name="help")
async def help_command(ctx):
    """Show contributor bot commands."""
    if ctx.channel.id != ONBOARDING_CH:
        return
    embed = discord.Embed(
        title="Nexus Contributor Bot — Befehle",
        color=0x5865F2,
    )
    embed.add_field(name="`!apply <github-username>`", value="Als Contributor anmelden und verifizieren", inline=False)
    embed.add_field(name="`!status [github-username]`", value="Contributor-Status pruefen", inline=False)
    embed.add_field(name="`!help`", value="Diese Hilfe anzeigen", inline=False)
    await ctx.send(embed=embed)


def main():
    print("Starting Nexus Contributor Bot...")
    bot.run(DISCORD_TOKEN)


if __name__ == "__main__":
    main()