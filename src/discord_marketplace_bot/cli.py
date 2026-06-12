from __future__ import annotations

import argparse
import asyncio
import logging
import os
from pathlib import Path

from dotenv import load_dotenv

from discord_marketplace_bot.config import ConfigError, load_config
from discord_marketplace_bot.render import render_status_text
from discord_marketplace_bot.runtime import run_bot
from discord_marketplace_bot.setup_runner import run_setup

DEFAULT_CONFIG_PATH = Path("config/server.yaml")


def main() -> None:
    load_dotenv()

    parser = argparse.ArgumentParser(
        prog="discord-marketplace",
        description="Configura e opera um servidor Discord de marketplace permitido.",
    )
    parser.add_argument(
        "--config",
        default=os.getenv("DISCORD_CONFIG_PATH", str(DEFAULT_CONFIG_PATH)),
        help="Caminho do YAML de configuracao.",
    )

    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("validate", help="Valida YAML sem chamar a API do Discord.")
    subparsers.add_parser("setup", help="Cria/atualiza estrutura no servidor Discord.")
    subparsers.add_parser("run", help="Roda o bot permanente com slash commands.")

    args = parser.parse_args()
    logging.basicConfig(
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        level=os.getenv("LOG_LEVEL", "INFO").upper(),
    )

    try:
        config = load_config(args.config)
    except ConfigError as exc:
        raise SystemExit(f"Config invalida: {exc}") from exc

    if args.command == "validate":
        print("Config valida.")
        print(render_status_text(config))
        return

    token = _required_env("DISCORD_BOT_TOKEN")
    guild_id = int(_required_env("DISCORD_GUILD_ID"))

    if args.command == "setup":
        summary = asyncio.run(run_setup(token, guild_id, config))
        print(summary)
        return

    if args.command == "run":
        run_bot(token, guild_id, config)
        return

    raise SystemExit(f"Comando desconhecido: {args.command}")


def _required_env(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise SystemExit(f"Configure {name} no arquivo .env.")
    return value
