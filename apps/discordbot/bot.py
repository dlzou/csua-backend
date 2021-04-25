import logging
import threading
import asyncio
import unicodedata
from functools import partial
import datetime, schedule, time
from decouple import config
import discord
from discord.embeds import Embed
from discord.utils import get
from django.core.validators import validate_email
from django.core.exceptions import ValidationError

from .utils import send_verify_mail
from .annoucements import event_checker

intents = discord.Intents.all()
intents.presences = False

TOKEN = config("DISCORD_TOKEN", default="")
CSUA_GUILD_ID = config("TEST_GUILD", default=784902200102354985, cast=int)
CSUA_PHILBOT_CLIENT_ID = config("BOT_ID", default=737930184837300274, cast=int)
HOSER_ROLE_ID = config("TEST_ROLE", default=785418569412116513, cast=int)  # Verified
DEBUG_CHANNEL_ID = config("DEBUG_CHANNEL", default=788989977794707456, cast=int)
ANNOUNCEMENTS_CHANNEL_ID = config("ANNOUNCEMENTS_CHANNEL", default=784902200102354989, cast=int) # set to chatter for testing
TIMEOUT_SECS = 10
ANI_NRUSIMHA_ID = 168539105704017920

logger = logging.getLogger(__name__)


class CSUAClient(discord.Client):
    async def on_ready(self):
        print(f"{self.user} has connected to Discord")
        self.is_phillip = self.user.id == CSUA_PHILBOT_CLIENT_ID
        csua_bot.announcements_thread = threading.Thread(target=csua_bot.event_announcement, daemon=True)
        csua_bot.announcements_thread.start()
        if self.is_phillip:
            print("Phillip is in the Office")
            self.csua_guild = get(self.guilds, id=CSUA_GUILD_ID)
            self.test_channel = get(self.csua_guild.channels, id=DEBUG_CHANNEL_ID)
            self.hoser_role = get(self.csua_guild.roles, id=HOSER_ROLE_ID)
            # if self.csua_guild is not None and self.test_channel is not None and self.hoser_role is not None:
            #     await self.test_channel.send("booting up successfully into phillip_debug channel")

    async def verify_member_email(self, user):
        channel = user.dm_channel

        def check_msg(msg):
            return msg.channel == channel

        got_email = False
        while not got_email:
            msg = await self.wait_for("message", check=check_msg)
            try:
                validate_email(msg.content)
                if "@berkeley.edu" in msg.content:
                    got_email = True
                    await channel.send(
                        f"Sending a an email to verify {user.name} to {msg.content}"
                    )
                    send_verify_mail(msg.content, user.name)
                else:
                    await channel.send(
                        f"{msg.content} is not a berkeley email. Please fix this"
                    )
            except ValidationError as e:
                await channel.send(
                    f"{msg.content} is not a valid email. Please try again. Details: ",
                    e,
                )

    async def on_message(self, message):
        if message.author == self.user:
            return
        # Reading rules and verification
        msg = message.content.lower()
        if "hkn" in msg and "ieee" in msg:
            await message.channel.send("Do I need to retrieve the stick?")
        if "is typing" in msg:
            await message.channel.send("unoriginal")
        if msg.count("cpma") >= 2:
            for emoji in emoji_letters("wtfiscpma"):
                await message.add_reaction(emoji)
        elif "based" in msg:
            for emoji in emoji_letters("based"):
                await message.add_reaction(emoji)
            await message.add_reaction("😎")
        elif "tree" in msg or "stanford" in msg or "stanfurd" in msg:
            emoji = unicodedata.lookup(
                "EVERGREEN TREE"
            )  # todo: add official <:tree:744335009002815609>
  
            await message.add_reaction(emoji)
        elif "drip" in msg or "👟" in msg or "🥵" in msg:
            for emoji in emoji_letters("drip"):
                await message.add_reaction(emoji)
            await message.add_reaction("👟")
        if message.author.id == ANI_NRUSIMHA_ID:
            emoji = get(self.emojis, name="AniChamp")
            if emoji:
                await message.add_reaction(emoji)
            else:
                for emoji in emoji_letters("ANI"):
                    await message.add_reaction(emoji)

    async def on_member_join(self, member):
        msg = await member.send(
            "Welcome to the CSUA discord server! First, read the rules in #landing-zone. Thumbs up this message if you agree"
        )
        await self.test_channel.send(f"Sent initial discord message to {member}")

        def check_thumb(react, _):
            return react.message == msg and str(react.emoji) == "👍"  # thumbs

        await self.wait_for("reaction_add", check=check_thumb)
        await self.test_channel.send(f"{member} read rules")
        await member.send(
            "Verify your berkeley.edu email to gain access. First, pleast type your email. Please contact a moderator if you have any issues."
        )

        await self.test_channel.send(f"{member} was prompted for email")
        await self.verify_member_email(member)
        if self.is_phillip:
            await self.test_channel.send(f"{member} was sent registration email")

    


def emoji_letters(chars):
    return [unicodedata.lookup(f"REGIONAL INDICATOR SYMBOL LETTER {c}") for c in chars]


class CSUABot:
    """
    Wraps CSUAClient by abstracting thread and event loop logic.

    All the discord.Client coroutines must be called using
    `asyncio.run_coroutine_threadsafe` because the client is running inside an
    event loop in a separate thread. Event loops are one per-thread, and Django
    can't handle async code, so a separate thread is used instead.
    """

    def __init__(self):
        self.loop = asyncio.new_event_loop()
        self.thread = threading.Thread(target=self._start, daemon=True)
        
        self.running = True
        self.thread.start()

    def _start(self):
        asyncio.set_event_loop(self.loop)
        self.client = CSUAClient(intents=intents)
        try:
            self.loop.run_until_complete(self.client.start(TOKEN))
        finally:
            self.loop.run_until_complete(self.client.logout())
            self.loop.close()

    def promote_user_to_hoser(self, tag):
        if not hasattr(self.client, "csua_guild"):
            client = self.client
            print(client)
        member = self.client.csua_guild.get_member_named(tag)
        if member:
            asyncio.run_coroutine_threadsafe(
                member.add_roles(self.client.hoser_role), self.loop
            ).result(TIMEOUT_SECS)
            asyncio.run_coroutine_threadsafe(
                self.client.test_channel.send(f"verified {tag}"), self.loop
            ).result(TIMEOUT_SECS)
            return True
        return False

    def event_announcement(self):
        print('Announcements Thread started...')
        
        times_msg = {
            "week": "NEXT WEEK",
            "today": "TODAY",
            "tomorrow": "TOMORROW",
            "hour": "IN 1 HOUR",
            "now": "NOW",
        }
        
        def announcer(time_before):

            events = event_checker(time_before)

            if events:
                msg = f"**What's happening {times_msg[time_before]}**"
                asyncio.run_coroutine_threadsafe(
                        self.client.get_channel(ANNOUNCEMENTS_CHANNEL_ID).send(msg), self.loop
                    ).result(TIMEOUT_SECS)
                print('hey hey hey time to check') # debugging

                send_embed(events)
        
        def send_embed(events):
            for event in events:
                embed = discord.Embed(
                    title=event.name,
                    description=event.description,
                    colour=discord.Colour.red()
                )
                embed.add_field(name='Date', value=event.date, inline=True)
                embed.add_field(name='Time', value=event.get_time_string())
                embed.add_field(name='Link', value=event.link)
                asyncio.run_coroutine_threadsafe(
                    self.client.get_channel(ANNOUNCEMENTS_CHANNEL_ID).send(embed=embed), self.loop
                ).result(TIMEOUT_SECS)

        
        schedule.every().sunday.at("17:00").do(partial(announcer, "week"))
        schedule.every().day.at("08:00").do(partial(announcer, "tomorrow"))
        schedule.every().day.at("08:00").do(partial(announcer, "today"))
        schedule.every().hour.do(partial(announcer, "hour"))
        schedule.every(30).minutes.do(partial(announcer, "now"))

        # For debugging
        # schedule.every(10).seconds.do(partial(announcer, "week"))
        # schedule.every(10).seconds.do(partial(announcer, "tomorrow"))
        # schedule.every(10).seconds.do(partial(announcer, "today"))
        # schedule.every(10).seconds.do(partial(announcer, "hour"))
        # schedule.every(10).seconds.do(partial(announcer, "now"))

        while True:
            schedule.run_pending()
            time.sleep(5)
            
                

if TOKEN:
    csua_bot = CSUABot()
else:
    csua_bot = None
