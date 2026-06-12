from __future__ import annotations

from dataclasses import dataclass

from discord_marketplace_bot.config import (
    CatalogSectionConfig,
    MessageConfig,
    ServerConfig,
)

MANAGED_FOOTER_PREFIX = "digital-market-managed"
MAX_FIELD_VALUE = 1024


@dataclass(frozen=True)
class EmbedFieldSpec:
    name: str
    value: str
    inline: bool = False


@dataclass(frozen=True)
class EmbedSpec:
    key: str
    title: str
    description: str
    color: int
    fields: tuple[EmbedFieldSpec, ...] = ()

    @property
    def footer(self) -> str:
        return managed_footer(self.key)


def managed_footer(key: str) -> str:
    return f"{MANAGED_FOOTER_PREFIX}:{key}"


def parse_color(value: str) -> int:
    raw = value.strip()
    if raw.startswith("#"):
        raw = raw[1:]
    if raw.lower().startswith("0x"):
        raw = raw[2:]

    try:
        color = int(raw, 16)
    except ValueError as exc:
        raise ValueError(f"Cor invalida: {value}") from exc

    if not 0 <= color <= 0xFFFFFF:
        raise ValueError(f"Cor fora do intervalo RGB: {value}")
    return color


def render_message_embed(message: MessageConfig, config: ServerConfig) -> EmbedSpec:
    return EmbedSpec(
        key=f"message:{message.key}",
        title=message.title,
        description=message.body.strip(),
        color=parse_color(config.server.accent_color),
        fields=tuple(
            EmbedFieldSpec(field.name, _clip(field.value), inline=False)
            for field in message.fields
        ),
    )


def render_catalog_embed(section: CatalogSectionConfig, config: ServerConfig) -> EmbedSpec:
    return EmbedSpec(
        key=f"catalog:{section.key}",
        title=section.title,
        description=section.description.strip(),
        color=parse_color(config.server.accent_color),
        fields=tuple(_render_catalog_item(item) for item in section.items),
    )


def render_status_text(config: ServerConfig) -> str:
    channel_count = sum(len(category.channels) for category in config.categories)
    return (
        f"Servidor: {config.server.name}\n"
        f"Cargos: {len(config.roles)}\n"
        f"Categorias: {len(config.categories)}\n"
        f"Canais: {channel_count}\n"
        f"Mensagens gerenciadas: {len(config.messages)}\n"
        f"Secoes de catalogo: {len(config.catalog)}"
    )


def _render_catalog_item(item) -> EmbedFieldSpec:
    value = f"Preco: {item.price}\n{item.description}"
    return EmbedFieldSpec(item.name, _clip(value), inline=False)


def _clip(value: str) -> str:
    text = value.strip()
    if len(text) <= MAX_FIELD_VALUE:
        return text
    return text[: MAX_FIELD_VALUE - 3].rstrip() + "..."
