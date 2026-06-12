from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

PROHIBITED_CATALOG_TERMS = (
    "discord nitro",
    "nitro irregular",
    "conta discord",
    "discord account",
    "token de usuario",
    "user token",
    "selfbot",
    "self-bot",
    "convite customizado",
    "custom invite",
    "vanity url",
)


class ConfigError(ValueError):
    """Raised when the server configuration is not safe or usable."""


@dataclass(frozen=True)
class FieldConfig:
    name: str
    value: str


@dataclass(frozen=True)
class RoleConfig:
    key: str
    name: str
    color: str = "#5865F2"
    hoist: bool = False
    mentionable: bool = False
    permissions: tuple[str, ...] = ()


@dataclass(frozen=True)
class ChannelConfig:
    key: str
    name: str
    topic: str = ""
    type: str = "text"
    private: bool = False
    allowed_role_keys: tuple[str, ...] = ()


@dataclass(frozen=True)
class CategoryConfig:
    key: str
    name: str
    private: bool = False
    allowed_role_keys: tuple[str, ...] = ()
    channels: tuple[ChannelConfig, ...] = ()


@dataclass(frozen=True)
class MessageConfig:
    key: str
    channel: str
    title: str
    body: str
    fields: tuple[FieldConfig, ...] = ()


@dataclass(frozen=True)
class CatalogItemConfig:
    name: str
    price: str
    description: str


@dataclass(frozen=True)
class CatalogSectionConfig:
    key: str
    channel: str
    title: str
    description: str
    items: tuple[CatalogItemConfig, ...] = ()


@dataclass(frozen=True)
class ServerSettings:
    name: str
    apply_name: bool
    accent_color: str
    archive_unmanaged: bool = False
    archive_category_name: str = "ARQUIVO"


@dataclass(frozen=True)
class SalesSettings:
    enabled: bool = True
    carts_category_name: str = "Carrinhos"
    closed_carts_category_name: str = "Carrinhos fechados"
    logs_channel_name: str = "logs-vendas"
    staff_role_key: str = "staff"


@dataclass(frozen=True)
class ServerConfig:
    server: ServerSettings
    roles: tuple[RoleConfig, ...] = ()
    categories: tuple[CategoryConfig, ...] = ()
    messages: tuple[MessageConfig, ...] = ()
    catalog: tuple[CatalogSectionConfig, ...] = ()
    sales: SalesSettings = field(default_factory=SalesSettings)
    source_path: Path | None = None

    @property
    def channels_by_key(self) -> dict[str, ChannelConfig]:
        return {
            channel.key: channel
            for category in self.categories
            for channel in category.channels
        }

    @property
    def roles_by_key(self) -> dict[str, RoleConfig]:
        return {role.key: role for role in self.roles}


def load_config(path: str | Path) -> ServerConfig:
    config_path = Path(path)
    try:
        raw = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ConfigError(f"Arquivo de config nao encontrado: {config_path}") from exc
    except yaml.YAMLError as exc:
        raise ConfigError(f"YAML invalido em {config_path}: {exc}") from exc

    if not isinstance(raw, dict):
        raise ConfigError("A config precisa ser um objeto YAML no topo.")

    config = parse_config(raw, config_path)
    validate_config(config)
    return config


def parse_config(raw: dict[str, Any], source_path: Path | None = None) -> ServerConfig:
    server_raw = _require_dict(raw, "server")
    server = ServerSettings(
        name=_require_str(server_raw, "name"),
        apply_name=bool(server_raw.get("apply_name", True)),
        accent_color=str(server_raw.get("accent_color", "#5865F2")),
        archive_unmanaged=bool(server_raw.get("archive_unmanaged", False)),
        archive_category_name=str(server_raw.get("archive_category_name", "ARQUIVO")).strip()
        or "ARQUIVO",
    )

    roles = tuple(_parse_role(item) for item in _optional_list(raw, "roles"))
    categories = tuple(_parse_category(item) for item in _optional_list(raw, "categories"))
    messages = tuple(_parse_message(item) for item in _optional_list(raw, "messages"))
    catalog = tuple(_parse_catalog_section(item) for item in _optional_list(raw, "catalog"))
    sales = _parse_sales_settings(raw.get("sales", {}))

    return ServerConfig(
        server=server,
        roles=roles,
        categories=categories,
        messages=messages,
        catalog=catalog,
        sales=sales,
        source_path=source_path,
    )


def validate_config(config: ServerConfig) -> None:
    _ensure_unique("role key", (role.key for role in config.roles))
    _ensure_unique("role name", (role.name for role in config.roles))
    _ensure_unique("category key", (category.key for category in config.categories))
    _ensure_unique("category name", (category.name for category in config.categories))
    _ensure_unique("message key", (message.key for message in config.messages))
    _ensure_unique("catalog key", (section.key for section in config.catalog))

    channels = config.channels_by_key
    _ensure_unique("channel key", channels.keys())
    _ensure_unique("channel name", (channel.name for channel in channels.values()))

    role_keys = set(config.roles_by_key)
    if config.sales.enabled and config.sales.staff_role_key not in role_keys:
        raise ConfigError(f"Sales staff_role_key inexistente: {config.sales.staff_role_key}")

    for category in config.categories:
        missing_roles = set(category.allowed_role_keys) - role_keys
        if missing_roles:
            raise ConfigError(
                f"Categoria {category.key} referencia cargos inexistentes: "
                f"{', '.join(sorted(missing_roles))}"
            )
        for channel in category.channels:
            missing_channel_roles = set(channel.allowed_role_keys) - role_keys
            if missing_channel_roles:
                raise ConfigError(
                    f"Canal {channel.key} referencia cargos inexistentes: "
                    f"{', '.join(sorted(missing_channel_roles))}"
                )

    for message in config.messages:
        if message.channel not in channels:
            raise ConfigError(
                f"Mensagem {message.key} referencia canal inexistente: {message.channel}"
            )

    for section in config.catalog:
        if section.channel not in channels:
            raise ConfigError(
                f"Catalogo {section.key} referencia canal inexistente: {section.channel}"
            )
        if not section.items:
            raise ConfigError(f"Catalogo {section.key} precisa ter ao menos um item.")
        _validate_catalog_policy(section)


def _parse_role(raw: Any) -> RoleConfig:
    item = _as_dict(raw, "role")
    return RoleConfig(
        key=_require_str(item, "key"),
        name=_require_str(item, "name"),
        color=str(item.get("color", "#5865F2")),
        hoist=bool(item.get("hoist", False)),
        mentionable=bool(item.get("mentionable", False)),
        permissions=tuple(str(permission) for permission in item.get("permissions", [])),
    )


def _parse_category(raw: Any) -> CategoryConfig:
    item = _as_dict(raw, "category")
    return CategoryConfig(
        key=_require_str(item, "key"),
        name=_require_str(item, "name"),
        private=bool(item.get("private", False)),
        allowed_role_keys=tuple(str(role_key) for role_key in item.get("allowed_role_keys", [])),
        channels=tuple(_parse_channel(channel) for channel in item.get("channels", [])),
    )


def _parse_channel(raw: Any) -> ChannelConfig:
    item = _as_dict(raw, "channel")
    return ChannelConfig(
        key=_require_str(item, "key"),
        name=_require_str(item, "name"),
        topic=str(item.get("topic", "")),
        type=str(item.get("type", "text")),
        private=bool(item.get("private", False)),
        allowed_role_keys=tuple(str(role_key) for role_key in item.get("allowed_role_keys", [])),
    )


def _parse_message(raw: Any) -> MessageConfig:
    item = _as_dict(raw, "message")
    return MessageConfig(
        key=_require_str(item, "key"),
        channel=_require_str(item, "channel"),
        title=_require_str(item, "title"),
        body=_require_str(item, "body"),
        fields=tuple(_parse_field(field) for field in item.get("fields", [])),
    )


def _parse_field(raw: Any) -> FieldConfig:
    item = _as_dict(raw, "field")
    return FieldConfig(
        name=_require_str(item, "name"),
        value=_require_str(item, "value"),
    )


def _parse_catalog_section(raw: Any) -> CatalogSectionConfig:
    item = _as_dict(raw, "catalog section")
    return CatalogSectionConfig(
        key=_require_str(item, "key"),
        channel=_require_str(item, "channel"),
        title=_require_str(item, "title"),
        description=_require_str(item, "description"),
        items=tuple(_parse_catalog_item(catalog_item) for catalog_item in item.get("items", [])),
    )


def _parse_sales_settings(raw: Any) -> SalesSettings:
    item = _as_dict(raw, "sales") if raw else {}
    return SalesSettings(
        enabled=bool(item.get("enabled", True)),
        carts_category_name=str(item.get("carts_category_name", "Carrinhos")).strip()
        or "Carrinhos",
        closed_carts_category_name=str(
            item.get("closed_carts_category_name", "Carrinhos fechados")
        ).strip()
        or "Carrinhos fechados",
        logs_channel_name=str(item.get("logs_channel_name", "logs-vendas")).strip()
        or "logs-vendas",
        staff_role_key=str(item.get("staff_role_key", "staff")).strip() or "staff",
    )


def _parse_catalog_item(raw: Any) -> CatalogItemConfig:
    item = _as_dict(raw, "catalog item")
    return CatalogItemConfig(
        name=_require_str(item, "name"),
        price=_require_str(item, "price"),
        description=_require_str(item, "description"),
    )


def _validate_catalog_policy(section: CatalogSectionConfig) -> None:
    chunks: list[str] = [section.title, section.description]
    for item in section.items:
        chunks.extend([item.name, item.price, item.description])

    text = " ".join(chunks).casefold()
    blocked_terms = [term for term in PROHIBITED_CATALOG_TERMS if term in text]
    if blocked_terms:
        raise ConfigError(
            f"Catalogo {section.key} contem termo bloqueado: {', '.join(blocked_terms)}"
        )


def _require_dict(raw: dict[str, Any], key: str) -> dict[str, Any]:
    if key not in raw:
        raise ConfigError(f"Campo obrigatorio ausente: {key}")
    return _as_dict(raw[key], key)


def _require_str(raw: dict[str, Any], key: str) -> str:
    value = raw.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ConfigError(f"Campo obrigatorio invalido: {key}")
    return value.strip()


def _optional_list(raw: dict[str, Any], key: str) -> list[Any]:
    value = raw.get(key, [])
    if not isinstance(value, list):
        raise ConfigError(f"Campo precisa ser lista: {key}")
    return value


def _as_dict(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ConfigError(f"Item invalido em {label}: esperado objeto.")
    return value


def _ensure_unique(label: str, values: Any) -> None:
    seen: set[str] = set()
    duplicates: set[str] = set()
    for raw_value in values:
        value = str(raw_value).casefold()
        if value in seen:
            duplicates.add(str(raw_value))
        seen.add(value)

    if duplicates:
        raise ConfigError(f"{label} duplicado: {', '.join(sorted(duplicates))}")
