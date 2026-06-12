from __future__ import annotations

import logging

import discord

from discord_marketplace_bot.config import ServerConfig
from discord_marketplace_bot.discord_ops import setup_guild

logger = logging.getLogger(__name__)


class SetupClient(discord.Client):
    def __init__(self, guild_id: int, config: ServerConfig) -> None:
        intents = discord.Intents.default()
        intents.guilds = True
        super().__init__(intents=intents)
        self.guild_id = guild_id
        self.config = config
        self.summary_text = ""
        self.failure: BaseException | None = None

    async def on_ready(self) -> None:
        try:
            guild = self.get_guild(self.guild_id)
            if guild is None:
                raise RuntimeError(
                    f"Servidor {self.guild_id} nao encontrado. "
                    "Confirme que o bot foi convidado para esse servidor."
                )

            logger.info("Configurando servidor %s (%s)", guild.name, guild.id)
            summary = await setup_guild(guild, self.config)
            self.summary_text = summary.as_text()
        except BaseException as exc:
            self.failure = exc
        finally:
            await self.close()


async def run_setup(token: str, guild_id: int, config: ServerConfig) -> str:
    client = SetupClient(guild_id, config)
    await client.start(token)
    if client.failure is not None:
        raise client.failure
    return client.summary_text
