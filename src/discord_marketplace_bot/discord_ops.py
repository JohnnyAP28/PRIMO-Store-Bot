from __future__ import annotations

from dataclasses import dataclass, field

import discord

from discord_marketplace_bot.config import (
    CategoryConfig,
    ChannelConfig,
    RoleConfig,
    ServerConfig,
)
from discord_marketplace_bot.render import (
    EmbedSpec,
    managed_footer,
    parse_color,
    render_catalog_embed,
    render_message_embed,
)

SETUP_REASON = "PRIMO Store automated setup"
REQUIRED_SETUP_PERMISSIONS = (
    "manage_guild",
    "manage_roles",
    "manage_channels",
    "manage_messages",
    "send_messages",
    "embed_links",
    "read_message_history",
    "view_channel",
)


@dataclass
class SetupSummary:
    created_roles: list[str] = field(default_factory=list)
    updated_roles: list[str] = field(default_factory=list)
    created_categories: list[str] = field(default_factory=list)
    updated_categories: list[str] = field(default_factory=list)
    created_channels: list[str] = field(default_factory=list)
    updated_channels: list[str] = field(default_factory=list)
    archived_channels: list[str] = field(default_factory=list)
    removed_categories: list[str] = field(default_factory=list)
    posted_messages: list[str] = field(default_factory=list)
    updated_messages: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def as_text(self) -> str:
        lines = ["Setup concluido."]
        sections = (
            ("Cargos criados", self.created_roles),
            ("Cargos atualizados", self.updated_roles),
            ("Categorias criadas", self.created_categories),
            ("Categorias atualizadas", self.updated_categories),
            ("Canais criados", self.created_channels),
            ("Canais atualizados", self.updated_channels),
            ("Canais arquivados", self.archived_channels),
            ("Categorias antigas removidas", self.removed_categories),
            ("Mensagens publicadas", self.posted_messages),
            ("Mensagens atualizadas", self.updated_messages),
            ("Avisos", self.warnings),
        )
        for label, values in sections:
            if values:
                lines.append(f"{label}: {', '.join(values)}")
        return "\n".join(lines)


async def setup_guild(guild: discord.Guild, config: ServerConfig) -> SetupSummary:
    summary = SetupSummary()
    validate_setup_permissions(guild)

    if config.server.apply_name and guild.name != config.server.name:
        if guild.me and guild.me.guild_permissions.manage_guild:
            await guild.edit(name=config.server.name, reason=SETUP_REASON)
        else:
            summary.warnings.append("Bot sem permissao manage_guild para renomear servidor.")

    roles_by_key = await ensure_roles(guild, config.roles, summary)
    if config.sales.enabled:
        await ensure_sales_scaffold(guild, config, roles_by_key, summary)

    if config.server.archive_unmanaged:
        archive_category = await ensure_archive_category(guild, config, roles_by_key, summary)
        await archive_unmanaged_channels(guild, config, archive_category, summary)

    categories_by_key = await ensure_categories(guild, config.categories, roles_by_key, summary)
    channels_by_key = await ensure_channels(
        guild, config.categories, categories_by_key, roles_by_key, summary
    )

    await publish_messages(channels_by_key, config, summary)
    await publish_catalog(channels_by_key, config, summary)
    return summary


def validate_setup_permissions(guild: discord.Guild) -> None:
    if guild.me is None:
        raise RuntimeError("Nao foi possivel identificar o membro do bot no servidor.")
    permissions = guild.me.guild_permissions
    if permissions.administrator:
        return
    missing = [p for p in REQUIRED_SETUP_PERMISSIONS if not getattr(permissions, p)]
    if missing:
        raise RuntimeError(
            f"Bot sem permissoes: {', '.join(missing)}. "
            "Reconvide o bot com permissoes de administrador."
        )


async def publish_catalog_for_guild(guild: discord.Guild, config: ServerConfig) -> SetupSummary:
    summary = SetupSummary()
    channels_by_key = {
        channel_config.key: _find_text_channel(guild, channel_config.name)
        for category in config.categories
        for channel_config in category.channels
    }
    missing = [key for key, channel in channels_by_key.items() if channel is None]
    if missing:
        summary.warnings.append(f"Canais ausentes: {', '.join(sorted(missing))}")
    await publish_catalog(
        {key: channel for key, channel in channels_by_key.items() if channel is not None},
        config, summary
    )
    return summary


async def ensure_roles(guild, roles, summary):
    roles_by_key = {}
    for role_config in roles:
        color = discord.Colour(parse_color(role_config.color))
        permissions = _permissions_from_names(role_config.permissions)
        role = discord.utils.get(guild.roles, name=role_config.name)
        if role is None:
            role = await guild.create_role(
                name=role_config.name, permissions=permissions, colour=color,
                hoist=role_config.hoist, mentionable=role_config.mentionable, reason=SETUP_REASON
            )
            summary.created_roles.append(role_config.name)
        else:
            needs_update = (
                role.permissions.value != permissions.value
                or role.colour.value != color.value
                or role.hoist != role_config.hoist
                or role.mentionable != role_config.mentionable
            )
            if needs_update:
                await role.edit(permissions=permissions, colour=color,
                                hoist=role_config.hoist, mentionable=role_config.mentionable,
                                reason=SETUP_REASON)
                summary.updated_roles.append(role_config.name)
        roles_by_key[role_config.key] = role
    return roles_by_key


async def ensure_archive_category(guild, config, roles_by_key, summary):
    name = config.server.archive_category_name
    overwrites = _private_overwrites(guild, roles_by_key, ("staff",))
    category = discord.utils.get(guild.categories, name=name)
    if category is None:
        category = await guild.create_category(name=name, overwrites=overwrites, reason=SETUP_REASON)
        summary.created_categories.append(name)
        return category
    await category.edit(overwrites=overwrites, reason=SETUP_REASON)
    summary.updated_categories.append(name)
    return category


async def ensure_sales_scaffold(guild, config, roles_by_key, summary):
    staff_role_keys = (config.sales.staff_role_key,)
    for category_name in (config.sales.carts_category_name, config.sales.closed_carts_category_name):
        category = discord.utils.get(guild.categories, name=category_name)
        overwrites = _private_overwrites(guild, roles_by_key, staff_role_keys)
        if category is None:
            await guild.create_category(name=category_name, overwrites=overwrites, reason=SETUP_REASON)
            summary.created_categories.append(category_name)
        else:
            await category.edit(overwrites=overwrites, reason=SETUP_REASON)
            summary.updated_categories.append(category_name)
    carts_category = discord.utils.get(guild.categories, name=config.sales.carts_category_name)
    if carts_category is None:
        return
    log_channel = _find_text_channel(guild, config.sales.logs_channel_name)
    if log_channel is None:
        await guild.create_text_channel(
            name=config.sales.logs_channel_name,
            topic="Logs privados de carrinhos, pagamentos e entregas.",
            category=carts_category,
            overwrites=_private_overwrites(guild, roles_by_key, staff_role_keys),
            reason=SETUP_REASON
        )
        summary.created_channels.append(config.sales.logs_channel_name)
    else:
        await log_channel.edit(
            topic="Logs privados de carrinhos, pagamentos e entregas.",
            category=carts_category,
            overwrites=_private_overwrites(guild, roles_by_key, staff_role_keys),
            reason=SETUP_REASON
        )
        summary.updated_channels.append(config.sales.logs_channel_name)


async def archive_unmanaged_channels(guild, config, archive_category, summary):
    desired_category_names = {category.name for category in config.categories}
    desired_category_names.add(config.server.archive_category_name)
    protected_category_names = set()
    if config.sales.enabled:
        protected_category_names.update({config.sales.carts_category_name, config.sales.closed_carts_category_name})
        desired_category_names.update(protected_category_names)
    desired_channel_names = {
        channel.name for category in config.categories for channel in category.channels
    }
    if config.sales.enabled:
        desired_channel_names.add(config.sales.logs_channel_name)
    for channel in list(guild.channels):
        if isinstance(channel, discord.CategoryChannel):
            continue
        if channel.name in desired_channel_names:
            continue
        if channel.category and channel.category.name in protected_category_names:
            continue
        if channel.category and channel.category.name == config.server.archive_category_name:
            continue
        await channel.edit(category=archive_category, reason=SETUP_REASON)
        summary.archived_channels.append(channel.name)
    for category in list(guild.categories):
        if category.name in desired_category_names:
            continue
        if category.channels:
            continue
        await category.delete(reason=SETUP_REASON)
        summary.removed_categories.append(category.name)


async def ensure_categories(guild, categories, roles_by_key, summary):
    categories_by_key = {}
    for position, category_config in enumerate(categories):
        overwrites = _category_overwrites(guild, category_config, roles_by_key)
        category = discord.utils.get(guild.categories, name=category_config.name)
        if category is None:
            create_kwargs = {"name": category_config.name, "reason": SETUP_REASON}
            if overwrites is not None:
                create_kwargs["overwrites"] = overwrites
            category = await guild.create_category(**create_kwargs)
            summary.created_categories.append(category_config.name)
        elif overwrites is not None:
            await category.edit(overwrites=overwrites, reason=SETUP_REASON)
            summary.updated_categories.append(category_config.name)
        if category.position != position:
            await category.edit(position=position, reason=SETUP_REASON)
        categories_by_key[category_config.key] = category
    return categories_by_key


async def ensure_channels(guild, categories, categories_by_key, roles_by_key, summary):
    channels_by_key = {}
    for category_config in categories:
        category = categories_by_key[category_config.key]
        for position, channel_config in enumerate(category_config.channels):
            overwrites = _channel_overwrites(guild, category_config, channel_config, roles_by_key)
            if channel_config.type != "text":
                summary.warnings.append(f"Tipo de canal nao suportado: {channel_config.key}")
                continue
            channel = _find_text_channel(guild, channel_config.name)
            if channel is None:
                create_kwargs = {"name": channel_config.name, "topic": channel_config.topic,
                                 "category": category, "position": position, "reason": SETUP_REASON}
                if overwrites is not None:
                    create_kwargs["overwrites"] = overwrites
                channel = await guild.create_text_channel(**create_kwargs)
                summary.created_channels.append(channel_config.name)
            else:
                edit_kwargs = {"topic": channel_config.topic, "category": category,
                               "position": position, "reason": SETUP_REASON}
                if overwrites is not None:
                    edit_kwargs["overwrites"] = overwrites
                await channel.edit(**edit_kwargs)
                summary.updated_channels.append(channel_config.name)
            channels_by_key[channel_config.key] = channel
    return channels_by_key


async def publish_messages(channels_by_key, config, summary):
    for message in config.messages:
        channel = channels_by_key.get(message.channel)
        if channel is None:
            summary.warnings.append(f"Canal ausente para mensagem {message.key}: {message.channel}")
            continue
        spec = render_message_embed(message, config)
        await upsert_embed(channel, spec, summary)


async def publish_catalog(channels_by_key, config, summary):
    for section in config.catalog:
        channel = channels_by_key.get(section.channel)
        if channel is None:
            summary.warnings.append(f"Canal ausente para catalogo {section.key}: {section.channel}")
            continue
        spec = render_catalog_embed(section, config)
        await upsert_embed(channel, spec, summary)


async def upsert_embed(channel, spec, summary):
    existing = await find_managed_message(channel, spec.key)
    embed = _to_discord_embed(spec)
    if existing is None:
        await channel.send(embed=embed)
        summary.posted_messages.append(spec.key)
    else:
        await existing.edit(embed=embed)
        summary.updated_messages.append(spec.key)


async def find_managed_message(channel, key):
    footer = managed_footer(key)
    async for message in channel.history(limit=50):
        if channel.guild.me is not None and message.author.id != channel.guild.me.id:
            continue
        for embed in message.embeds:
            if embed.footer and embed.footer.text == footer:
                return message
    return None


def _to_discord_embed(spec):
    embed = discord.Embed(title=spec.title, description=spec.description, colour=discord.Colour(spec.color))
    for field in spec.fields:
        embed.add_field(name=field.name, value=field.value, inline=field.inline)
    embed.set_footer(text=spec.footer)
    return embed


def _category_overwrites(guild, category, roles_by_key):
    if not category.private:
        return None
    return _private_overwrites(guild, roles_by_key, category.allowed_role_keys)


def _channel_overwrites(guild, category, channel, roles_by_key):
    if channel.private:
        allowed_role_keys = channel.allowed_role_keys or category.allowed_role_keys or ("staff",)
        return _private_overwrites(guild, roles_by_key, allowed_role_keys)
    return _category_overwrites(guild, category, roles_by_key)


def _private_overwrites(guild, roles_by_key, allowed_role_keys):
    overwrites = {guild.default_role: discord.PermissionOverwrite(view_channel=False)}
    for role_key in allowed_role_keys:
        role = roles_by_key.get(role_key)
        if role is None:
            continue
        overwrites[role] = discord.PermissionOverwrite(
            view_channel=True, send_messages=True, read_message_history=True
        )
    if guild.me is not None:
        overwrites[guild.me] = discord.PermissionOverwrite(
            view_channel=True, send_messages=True, read_message_history=True,
            manage_channels=True, manage_messages=True
        )
    return overwrites


def _permissions_from_names(names):
    permissions = discord.Permissions.none()
    for raw_name in names:
        name = raw_name.strip().lower()
        if not name:
            continue
        if not hasattr(permissions, name):
            raise ValueError(f"Permissao Discord desconhecida: {raw_name}")
        setattr(permissions, name, True)
    return permissions


def _find_text_channel(guild, name):
    channel = discord.utils.get(guild.text_channels, name=name)
    return channel if isinstance(channel, discord.TextChannel) else None
