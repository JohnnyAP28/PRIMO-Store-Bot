from __future__ import annotations

import discord
from discord import app_commands
from discord_marketplace_bot.sales_storage import SalesStore


def register_botconfig_command(bot, guild_object, store):
    @bot.tree.command(name="botconfig", description="Configura o bot: nome, avatar, webhooks, entrega automatica e comandos customizados.", guild=guild_object)
    @app_commands.checks.has_permissions(manage_guild=True)
    async def botconfig(interaction):
        await interaction.response.send_modal(BotConfigModal(bot, store))

    @botconfig.error
    async def botconfig_error(interaction, error):
        msg = "Erro ao abrir configuracao do bot."
        if isinstance(error, app_commands.MissingPermissions): msg = "Voce precisa da permissao Manage Server."
        if interaction.response.is_done(): await interaction.followup.send(msg, ephemeral=True)
        else: await interaction.response.send_message(msg, ephemeral=True)


class BotConfigModal(discord.ui.Modal):
    def __init__(self, bot, store):
        super().__init__(title="Configuracao do Bot")
        self.bot = bot; self.store = store
        cfg = store.get_bot_config()
        self.name_input = discord.ui.TextInput(label="Nome do bot (no servidor)", placeholder="Ex: PRIMO Store Oficial", max_length=32, required=False, default=bot.user.name if bot.user else "")
        self.avatar_input = discord.ui.TextInput(label="URL do avatar (imagem)", placeholder="https://...", max_length=400, required=False)
        self.webhook_input = discord.ui.TextInput(label="URL do Webhook de logs", placeholder="https://discord.com/api/webhooks/...", max_length=400, required=False, default=cfg.webhook_url)
        self.commands_input = discord.ui.TextInput(label="Comandos customizados (JSON ou pipe)", style=discord.TextStyle.paragraph, placeholder='Formato: nome:resposta|nome2:resposta2\nEx: regras:Leia as regras em <#canal>', max_length=1800, required=False, default=cfg.custom_commands)
        self.auto_delivery_input = discord.ui.TextInput(label="Entrega automatica (1=ativado, 0=desativado)", placeholder="1", max_length=1, required=False, default=cfg.auto_delivery_enabled or "1")
        self.add_item(self.name_input); self.add_item(self.avatar_input); self.add_item(self.webhook_input); self.add_item(self.commands_input); self.add_item(self.auto_delivery_input)

    async def on_submit(self, interaction):
        changes = []
        new_name = str(self.name_input.value).strip()
        if new_name and interaction.guild and interaction.guild.me:
            try: await interaction.guild.me.edit(nick=new_name); changes.append(f"Nome alterado para `{new_name}`")
            except discord.Forbidden: changes.append("Sem permissao para alterar o nome.")
            except discord.HTTPException as e: changes.append(f"Erro ao alterar nome: {e}")
        avatar_url = str(self.avatar_input.value).strip()
        if avatar_url:
            try:
                import httpx
                async with httpx.AsyncClient() as c:
                    r = await c.get(avatar_url)
                    if r.status_code == 200: await self.bot.user.edit(avatar=r.content); changes.append("Avatar atualizado.")
                    else: changes.append(f"Erro ao baixar avatar: HTTP {r.status_code}")
            except Exception as e: changes.append(f"Erro ao alterar avatar: {e}")
        cc = str(self.commands_input.value).strip()
        wu = str(self.webhook_input.value).strip()
        ad = str(self.auto_delivery_input.value).strip() == "1"
        self.store.set_bot_config(custom_commands=cc, webhook_url=wu, auto_delivery_enabled=ad)
        if cc: changes.append(f"{len([c for c in cc.split('|') if ':' in c])} comandos customizados salvos.")
        if wu: changes.append("Webhook de logs configurado.")
        changes.append(f"Entrega automatica: {'ativada' if ad else 'desativada'}.")
        await interaction.response.send_message("**Configuracoes salvas:**\n" + "\n".join(f"- {c}" for c in changes), ephemeral=True)


def register_custom_commands_handler(bot, store):
    @bot.event
    async def on_message(message):
        if message.author.bot: return
        cfg = store.get_bot_config()
        if not cfg.custom_commands: return
        cmds = _parse_custom_commands(cfg.custom_commands)
        content = message.content.strip()
        for trigger, response in cmds.items():
            if content.lower() == trigger.lower():
                await message.channel.send(response); return


def _parse_custom_commands(raw):
    if not raw.strip(): return {}
    result = {}
    if raw.strip().startswith("{"):
        import json
        try:
            data = json.loads(raw)
            if isinstance(data, dict): return {str(k): str(v) for k, v in data.items()}
        except json.JSONDecodeError: pass
    for part in raw.split("|"):
        part = part.strip()
        if ":" in part:
            k, _, v = part.partition(":"); result[k.strip()] = v.strip()
    return result
