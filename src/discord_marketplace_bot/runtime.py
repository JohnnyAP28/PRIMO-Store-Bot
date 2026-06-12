from __future__ import annotations

import logging
import os

import discord
from discord import app_commands

from discord_marketplace_bot.config import ServerConfig
from discord_marketplace_bot.botconfig import (
    register_botconfig_command,
    register_custom_commands_handler,
)
from discord_marketplace_bot.discord_ops import publish_catalog_for_guild
from discord_marketplace_bot.render import render_status_text
from discord_marketplace_bot.sales_runtime import (
    register_persistent_panel_views,
    register_sales_features,
)
from discord_marketplace_bot.sales_storage import SalesStore

logger = logging.getLogger(__name__)


def build_bot(config: ServerConfig, guild_id: int) -> discord.Client:
    intents = discord.Intents.default()
    intents.guilds = True
    intents.message_content = True  # Needed for custom commands

    bot = discord.Client(intents=intents)
    bot.tree = app_commands.CommandTree(bot)
    bot.server_config = config
    bot.sales_store = SalesStore(os.getenv("SALES_DB_PATH", "var/sales.sqlite"))
    guild_object = discord.Object(id=guild_id)
    bot_synced = False
    views_registered = False
    register_sales_features(bot, guild_object, config, bot.sales_store)
    register_botconfig_command(bot, guild_object, bot.sales_store)
    register_custom_commands_handler(bot, bot.sales_store)

    @bot.event
    async def on_ready() -> None:
        nonlocal bot_synced, views_registered
        logger.info("Bot conectado como %s", bot.user)
        if not views_registered:
            register_persistent_panel_views(bot, bot.sales_store, guild_id)
            views_registered = True
        if not bot_synced:
            await bot.tree.sync(guild=guild_object)
            bot_synced = True
            logger.info("Slash commands sincronizados no servidor %s", guild_id)

    @bot.tree.command(
        name="catalog_sync",
        description="Republica o catalogo a partir do YAML configurado.",
        guild=guild_object,
    )
    @app_commands.checks.has_permissions(manage_guild=True)
    async def catalog_sync(interaction: discord.Interaction) -> None:
        await interaction.response.defer(ephemeral=True, thinking=True)
        guild = interaction.guild
        if guild is None:
            await interaction.followup.send("Comando disponivel apenas no servidor.", ephemeral=True)
            return
        summary = await publish_catalog_for_guild(guild, config)
        await interaction.followup.send(summary.as_text(), ephemeral=True)

    @bot.tree.command(
        name="catalog_status",
        description="Mostra o status da configuracao do marketplace.",
        guild=guild_object,
    )
    @app_commands.checks.has_permissions(manage_guild=True)
    async def catalog_status(interaction: discord.Interaction) -> None:
        await interaction.response.send_message(render_status_text(config), ephemeral=True)

    @catalog_sync.error
    @catalog_status.error
    async def command_error(interaction, error):
        message = "Erro ao executar comando."
        if isinstance(error, app_commands.MissingPermissions):
            message = "Voce precisa da permissao Manage Server para usar este comando."
        if interaction.response.is_done():
            await interaction.followup.send(message, ephemeral=True)
        else:
            await interaction.response.send_message(message, ephemeral=True)
        logger.warning("Slash command error: %s", error)

    return bot


def run_bot(token: str, guild_id: int, config: ServerConfig) -> None:
    bot = build_bot(config, guild_id)
    bot.run(token)
