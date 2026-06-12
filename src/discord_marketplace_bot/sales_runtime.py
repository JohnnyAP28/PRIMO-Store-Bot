from __future__ import annotations

import re
from typing import Optional

import discord
from discord import app_commands

from discord_marketplace_bot.config import ServerConfig
from discord_marketplace_bot.render import parse_color
from discord_marketplace_bot.sales_storage import (
    Cart, SalesError, SalesOption, SalesPanel, SalesStore,
)

CART_STATUS_LABELS = {
    "aberto": "Aberto",
    "aguardando_pagamento": "Aguardando pagamento",
    "aguardando_confirmacao": "Aguardando confirmacao da staff",
    "pago": "Pago",
    "entregue": "Entregue",
    "cancelado": "Cancelado",
    "fechado": "Fechado",
}
TERMINAL_STATUSES = {"entregue", "cancelado", "fechado"}


def register_sales_features(bot, guild_object, config, store):
    bot.add_view(CartActionsView(store, config))

    @bot.tree.command(name="pix_config", description="Configura a chave PIX e QR Code dos carrinhos.", guild=guild_object)
    @app_commands.checks.has_permissions(manage_guild=True)
    async def pix_config(interaction, chave: str, qr_url: Optional[str] = None, qr_imagem: Optional[discord.Attachment] = None):
        qr_value = attachment_or_url(qr_imagem, qr_url)
        try: store.set_pix(chave, qr_value)
        except SalesError as exc: await interaction.response.send_message(str(exc), ephemeral=True); return
        embed = discord.Embed(title="PIX Configurado", description="Chave PIX configurada com sucesso. Use os botoes abaixo para copiar ou ver o QR Code.", colour=discord.Colour(parse_color(config.server.accent_color)))
        embed.add_field(name="Chave PIX (copie clicando no botao)", value=f"```\n{chave}\n```", inline=False)
        if qr_value: embed.set_image(url=qr_value)
        await interaction.response.send_message(embed=embed, view=PixCopyView(chave, qr_value), ephemeral=True)

    @bot.tree.command(name="venda_painel_criar", description="Cria um painel de venda completo com opcoes e publica em um so fluxo.", guild=guild_object)
    @app_commands.checks.has_permissions(manage_guild=True)
    async def venda_painel_criar(interaction, canal: discord.TextChannel, imagem_url: Optional[str] = None, imagem: Optional[discord.Attachment] = None, thumbnail_url: Optional[str] = None, thumbnail: Optional[discord.Attachment] = None):
        await interaction.response.send_modal(PanelFullCreateModal(store=store, channel=canal, image_url=attachment_or_url(imagem, imagem_url), thumbnail_url=attachment_or_url(thumbnail, thumbnail_url), config=config))

    @bot.tree.command(name="venda_opcao_add", description="Adiciona uma opcao/produto extra em um painel de venda existente.", guild=guild_object)
    @app_commands.checks.has_permissions(manage_guild=True)
    async def venda_opcao_add(interaction, painel_id: int, imagem_url: Optional[str] = None, imagem: Optional[discord.Attachment] = None):
        await interaction.response.send_modal(OptionCreateModal(store=store, panel_id=painel_id, image_url=attachment_or_url(imagem, imagem_url)))

    @bot.tree.command(name="venda_painel_publicar", description="Publica ou republica um painel de venda.", guild=guild_object)
    @app_commands.checks.has_permissions(manage_guild=True)
    async def venda_painel_publicar(interaction, painel_id: int):
        await interaction.response.defer(ephemeral=True, thinking=True)
        try: message = await publish_or_update_panel(interaction.client, config, store, painel_id)
        except SalesError as exc: await interaction.followup.send(str(exc), ephemeral=True); return
        await interaction.followup.send(f"Painel `{painel_id}` publicado em {message.channel.mention}.", ephemeral=True)

    @bot.tree.command(name="venda_painel_atualizar", description="Atualiza a mensagem publicada de um painel.", guild=guild_object)
    @app_commands.checks.has_permissions(manage_guild=True)
    async def venda_painel_atualizar(interaction, painel_id: int):
        await interaction.response.defer(ephemeral=True, thinking=True)
        try: message = await publish_or_update_panel(interaction.client, config, store, painel_id)
        except SalesError as exc: await interaction.followup.send(str(exc), ephemeral=True); return
        await interaction.followup.send(f"Painel `{painel_id}` atualizado em {message.channel.mention}.", ephemeral=True)

    @bot.tree.command(name="venda_listar", description="Lista paineis de venda cadastrados.", guild=guild_object)
    @app_commands.checks.has_permissions(manage_guild=True)
    async def venda_listar(interaction):
        panels = store.list_panels(guild_id=interaction.guild_id)
        if not panels: await interaction.response.send_message("Nenhum painel cadastrado.", ephemeral=True); return
        lines = []
        for p in panels[:20]:
            s = "ativo" if p.active else "inativo"
            pub = f"msg {p.message_id}" if p.message_id else "nao publicado"
            oc = len(store.get_options(p.id, True))
            lines.append(f"`{p.id}` - {p.title} ({s}, {pub}, {oc} opcoes)")
        await interaction.response.send_message("\n".join(lines), ephemeral=True)

    @bot.tree.command(name="venda_desativar", description="Desativa um painel de venda.", guild=guild_object)
    @app_commands.checks.has_permissions(manage_guild=True)
    async def venda_desativar(interaction, painel_id: int):
        panel = store.get_panel(painel_id)
        if panel is None: await interaction.response.send_message("Painel nao encontrado.", ephemeral=True); return
        store.set_panel_active(painel_id, False)
        await interaction.response.send_message(f"Painel `{painel_id}` desativado.", ephemeral=True)

    @bot.tree.command(name="venda_carrinhos", description="Lista carrinhos abertos ou pendentes.", guild=guild_object)
    @app_commands.checks.has_permissions(manage_guild=True)
    async def venda_carrinhos(interaction):
        carts = store.list_open_carts(guild_id=interaction.guild_id)
        if not carts: await interaction.response.send_message("Nenhum carrinho aberto.", ephemeral=True); return
        lines = []
        for cart in carts[:20]:
            opt = store.get_option(cart.option_id)
            label = opt.label if opt else f"opcao {cart.option_id}"
            lines.append(f"`{cart.id}` - {label} - {CART_STATUS_LABELS.get(cart.status, cart.status)}")
        await interaction.response.send_message("\n".join(lines), ephemeral=True)

    @pix_config.error
    @venda_painel_criar.error
    @venda_opcao_add.error
    @venda_painel_publicar.error
    @venda_painel_atualizar.error
    @venda_listar.error
    @venda_desativar.error
    @venda_carrinhos.error
    async def sales_command_error(interaction, error):
        msg = "Erro ao executar comando de vendas."
        if isinstance(error, app_commands.MissingPermissions): msg = "Voce precisa da permissao Manage Server."
        if interaction.response.is_done(): await interaction.followup.send(msg, ephemeral=True)
        else: await interaction.response.send_message(msg, ephemeral=True)


def register_persistent_panel_views(bot, store, guild_id):
    for panel in store.list_published_panels(guild_id=guild_id):
        if panel.message_id is None: continue
        bot.add_view(SalesPanelView(store, panel.id), message_id=panel.message_id)


class PanelFullCreateModal(discord.ui.Modal):
    def __init__(self, *, store, channel, image_url, thumbnail_url, config):
        super().__init__(title="Criar painel completo")
        self.store = store; self.channel = channel; self.image_url = image_url; self.thumbnail_url = thumbnail_url; self.config = config
        self.title_input = discord.ui.TextInput(label="Titulo do painel", placeholder="Ex: Assinaturas — PRIMO Store (use <a:emoji:id> para animados)", max_length=180)
        self.desc_input = discord.ui.TextInput(label="Descricao", style=discord.TextStyle.paragraph, placeholder="Texto principal do anuncio. Emojis animados: <a:nome:id>", max_length=1800)
        self.footer_input = discord.ui.TextInput(label="Rodape", required=False, placeholder="Ex: PRIMO Store - Entrega rapida e suporte via ticket", max_length=180)
        self.color_input = discord.ui.TextInput(label="Cor HEX", required=False, default="#8A2BE2", max_length=16)
        self.add_item(self.title_input); self.add_item(self.desc_input); self.add_item(self.footer_input); self.add_item(self.color_input)

    async def on_submit(self, interaction):
        if interaction.guild_id is None: await interaction.response.send_message("Use este comando dentro do servidor.", ephemeral=True); return
        try:
            parse_color(str(self.color_input.value or "#8A2BE2"))
            panel = self.store.create_panel(guild_id=interaction.guild_id, channel_id=self.channel.id, title=str(self.title_input.value), description=str(self.desc_input.value), image_url=self.image_url, thumbnail_url=self.thumbnail_url, footer=str(self.footer_input.value), color=str(self.color_input.value or "#8A2BE2"), created_by=interaction.user.id)
        except (SalesError, ValueError) as exc: await interaction.response.send_message(str(exc), ephemeral=True); return
        view = PanelBuildView(self.store, panel.id, self.config)
        await interaction.response.send_message(f"Painel `{panel.id}` criado: **{self.title_input.value}**\nUse os botoes abaixo para adicionar opcoes e publicar.", view=view, ephemeral=True)


class OptionCreateModal(discord.ui.Modal):
    def __init__(self, *, store, panel_id, image_url):
        super().__init__(title="Adicionar produto/opcao")
        self.store = store; self.panel_id = panel_id; self.image_url = image_url
        self.label_input = discord.ui.TextInput(label="Nome da opcao", placeholder="Ex: Plano mensal (use <a:emoji:id> para animados)", max_length=90)
        self.desc_input = discord.ui.TextInput(label="Descricao curta", placeholder="Aparece no menu de selecao.", max_length=90)
        self.price_input = discord.ui.TextInput(label="Valor", placeholder="Ex: R$ 19,90", max_length=60)
        self.details_input = discord.ui.TextInput(label="Detalhes (mostrado no painel e carrinho)", style=discord.TextStyle.paragraph, required=False, placeholder="Detalhes do produto visiveis para o cliente.", max_length=1200)
        self.add_item(self.label_input); self.add_item(self.desc_input); self.add_item(self.price_input); self.add_item(self.details_input)

    async def on_submit(self, interaction):
        try: option = self.store.add_option(panel_id=self.panel_id, label=str(self.label_input.value), description=str(self.desc_input.value), price=str(self.price_input.value), details=str(self.details_input.value), image_url=self.image_url)
        except SalesError as exc: await interaction.response.send_message(str(exc), ephemeral=True); return
        await interaction.response.send_message(f"Opcao `{option.id}` (`{self.label_input.value}`) adicionada ao painel `{self.panel_id}`.", ephemeral=True)


class OptionCreateWithDeliveryModal(discord.ui.Modal):
    def __init__(self, *, store, panel_id, image_url):
        super().__init__(title="Adicionar produto com entrega")
        self.store = store; self.panel_id = panel_id; self.image_url = image_url
        self.label_input = discord.ui.TextInput(label="Nome da opcao", placeholder="Ex: Conta Premium 1 mes (use <a:emoji:id> para animados)", max_length=90)
        self.desc_input = discord.ui.TextInput(label="Descricao curta", placeholder="Aparece no menu de selecao.", max_length=90)
        self.price_input = discord.ui.TextInput(label="Valor", placeholder="Ex: R$ 19,90", max_length=60)
        self.details_input = discord.ui.TextInput(label="Detalhes e entrega automatica", style=discord.TextStyle.paragraph, required=False, placeholder="Detalhes do produto + o que sera enviado automaticamente ao cliente apos pagamento.", max_length=1200)
        self.delivery_input = discord.ui.TextInput(label="Conteudo da entrega automatica", style=discord.TextStyle.paragraph, required=False, placeholder="Enviado automaticamente no canal do carrinho quando o staff marcar como ENTREGUE.", max_length=1800)
        self.add_item(self.label_input); self.add_item(self.desc_input); self.add_item(self.price_input); self.add_item(self.details_input); self.add_item(self.delivery_input)

    async def on_submit(self, interaction):
        try: option = self.store.add_option(panel_id=self.panel_id, label=str(self.label_input.value), description=str(self.desc_input.value), price=str(self.price_input.value), details=str(self.details_input.value), image_url=self.image_url, delivery_content=str(self.delivery_input.value))
        except SalesError as exc: await interaction.response.send_message(str(exc), ephemeral=True); return
        ds = "com entrega automatica" if str(self.delivery_input.value).strip() else "sem entrega automatica"
        await interaction.response.send_message(f"Opcao `{option.id}` (`{self.label_input.value}`) adicionada ao painel `{self.panel_id}` ({ds}).", ephemeral=True)


class PanelBuildView(discord.ui.View):
    def __init__(self, store, panel_id, config):
        super().__init__(timeout=600)
        self.store = store; self.panel_id = panel_id; self.config = config

    @discord.ui.button(label="Adicionar Opcao Simples", style=discord.ButtonStyle.primary, row=0)
    async def add_simple(self, interaction, _):
        await interaction.response.send_modal(OptionCreateModal(store=self.store, panel_id=self.panel_id, image_url=""))

    @discord.ui.button(label="Adicionar Opcao com Entrega", style=discord.ButtonStyle.success, row=0)
    async def add_with_delivery(self, interaction, _):
        await interaction.response.send_modal(OptionCreateWithDeliveryModal(store=self.store, panel_id=self.panel_id, image_url=""))

    @discord.ui.button(label="Publicar agora", style=discord.ButtonStyle.danger, row=1)
    async def publish(self, interaction, _):
        await interaction.response.defer(ephemeral=True, thinking=True)
        try: msg = await publish_or_update_panel(interaction.client, self.config, self.store, self.panel_id)
        except SalesError as exc: await interaction.followup.send(str(exc), ephemeral=True); return
        self.stop(); await interaction.followup.send(f"Painel `{self.panel_id}` publicado em {msg.channel.mention}.", ephemeral=True)

    @discord.ui.button(label="Ver opcoes", style=discord.ButtonStyle.secondary, row=1)
    async def list_options(self, interaction, _):
        opts = self.store.get_options(self.panel_id, False)
        if not opts: await interaction.response.send_message("Nenhuma opcao adicionada ainda.", ephemeral=True); return
        lines = [f"Painel `{self.panel_id}` — {len(opts)} opcoes:"]
        for o in opts[:25]:
            d = " [entrega auto]" if o.delivery_content else ""
            lines.append(f"  `{o.id}` - {o.label} - {o.price}{d}")
        await interaction.response.send_message("\n".join(lines), ephemeral=True)


class PixCopyView(discord.ui.View):
    def __init__(self, chave, qr_url):
        super().__init__(timeout=300); self.chave = chave; self.qr_url = qr_url

    @discord.ui.button(label="Copiar chave PIX", style=discord.ButtonStyle.primary)
    async def copy_pix(self, interaction, _):
        await interaction.response.send_message(f"Chave PIX (copie abaixo):\n```\n{self.chave}\n```", ephemeral=True)

    @discord.ui.button(label="Ver QR Code", style=discord.ButtonStyle.secondary)
    async def show_qr(self, interaction, _):
        if not self.qr_url: await interaction.response.send_message("QR Code nao configurado.", ephemeral=True); return
        embed = discord.Embed(title="QR Code PIX"); embed.set_image(url=self.qr_url)
        await interaction.response.send_message(embed=embed, ephemeral=True)


class SalesPanelView(discord.ui.View):
    def __init__(self, store, panel_id):
        super().__init__(timeout=None)
        panel = store.get_panel(panel_id); opts = store.get_options(panel_id, True)
        sel = [discord.SelectOption(label=o.label[:100], value=str(o.id), description=f"{o.price} - {o.description}"[:100]) for o in opts[:25]]
        if not sel: sel.append(discord.SelectOption(label="Nenhum produto disponivel", value="none", description="A staff ainda precisa adicionar opcoes."))
        self.add_item(SalesProductSelect(store=store, panel_id=panel_id, disabled=panel is None or not panel.active or not opts, options=sel))


class SalesProductSelect(discord.ui.Select):
    def __init__(self, *, store, panel_id, disabled, options):
        super().__init__(placeholder="Selecione um produto", min_values=1, max_values=1, options=options, disabled=disabled, custom_id=f"sales:select:{panel_id}")
        self.store = store; self.panel_id = panel_id

    async def callback(self, interaction):
        if not self.values or self.values[0] == "none": await interaction.response.send_message("Nenhum produto disponivel.", ephemeral=True); return
        if interaction.guild is None: await interaction.response.send_message("Use dentro do servidor.", ephemeral=True); return
        panel = self.store.get_panel(self.panel_id); option = self.store.get_option(int(self.values[0]))
        if panel is None or option is None or not panel.active or not option.active: await interaction.response.send_message("Produto indisponivel.", ephemeral=True); return
        await interaction.response.defer(ephemeral=True, thinking=True)
        ch = await create_cart_channel(guild=interaction.guild, config=getattr(interaction.client, "server_config"), customer=interaction.user)
        cart = self.store.create_cart(guild_id=interaction.guild.id, channel_id=ch.id, customer_id=interaction.user.id, panel_id=panel.id, option_id=option.id)
        await ch.edit(name=f"carrinho-{cart.id}-{slugify(interaction.user.display_name)}")
        msg = await ch.send(content=f"{interaction.user.mention} carrinho criado. A staff acompanha por aqui.", embed=build_cart_embed(self.store, cart), view=CartActionsView(self.store, getattr(interaction.client, "server_config")))
        self.store.set_cart_log_message(cart.id, msg.id)
        await log_sales_event(interaction.guild, getattr(interaction.client, "server_config"), f"Carrinho `{cart.id}` criado por {interaction.user.mention} para `{option.label}`.")
        await interaction.followup.send(f"Carrinho criado: {ch.mention}", ephemeral=True)


class CartActionsView(discord.ui.View):
    def __init__(self, store, config): super().__init__(timeout=None); self.store = store; self.config = config

    @discord.ui.button(label="Pagar", style=discord.ButtonStyle.success, custom_id="sales:cart:pay", row=0)
    async def pay(self, i, _): await self._update_cart(i, "aguardando_pagamento")
    @discord.ui.button(label="Ja paguei", style=discord.ButtonStyle.primary, custom_id="sales:cart:paid_notice", row=0)
    async def paid_notice(self, i, _): await self._update_cart(i, "aguardando_confirmacao")
    @discord.ui.button(label="Cancelar", style=discord.ButtonStyle.danger, custom_id="sales:cart:cancel", row=0)
    async def cancel(self, i, _): await self._update_cart(i, "cancelado", close_after=True)
    @discord.ui.button(label="Marcar pago", style=discord.ButtonStyle.secondary, custom_id="sales:cart:mark_paid", row=1)
    async def mark_paid(self, i, _): await self._update_cart(i, "pago", staff_only=True)
    @discord.ui.button(label="Entregar", style=discord.ButtonStyle.secondary, custom_id="sales:cart:deliver", row=1)
    async def deliver(self, i, _): await self._update_cart(i, "entregue", staff_only=True, close_after=True)
    @discord.ui.button(label="Fechar", style=discord.ButtonStyle.secondary, custom_id="sales:cart:close", row=1)
    async def close(self, i, _): await self._update_cart(i, "fechado", staff_only=True, close_after=True)

    async def _update_cart(self, interaction, status, *, staff_only=False, close_after=False):
        ctx = self._get_cart_context(interaction)
        if isinstance(ctx, str): await interaction.response.send_message(ctx, ephemeral=True); return
        cart, panel, option = ctx
        if cart.status in TERMINAL_STATUSES: await interaction.response.send_message("Este carrinho ja foi fechado.", ephemeral=True); return
        if staff_only and not is_staff(interaction, self.config): await interaction.response.send_message("Apenas staff pode usar esta acao.", ephemeral=True); return
        if not staff_only and interaction.user.id != cart.customer_id and not is_staff(interaction, self.config): await interaction.response.send_message("Apenas o cliente ou staff pode usar esta acao.", ephemeral=True); return
        self.store.update_cart_status(cart.id, status)
        uc = self.store.get_cart(cart.id)
        if uc is None: await interaction.response.send_message("Carrinho nao encontrado apos atualizar.", ephemeral=True); return
        if interaction.message: await interaction.message.edit(embed=build_cart_embed(self.store, uc), view=CartActionsView(self.store, self.config))
        await log_sales_event(interaction.guild, self.config, f"Carrinho `{cart.id}` alterado para `{CART_STATUS_LABELS.get(status, status)}` por {interaction.user.mention}.")
        if status == "entregue" and option.delivery_content: await _send_auto_delivery(interaction, cart, option)
        if close_after and isinstance(interaction.channel, discord.TextChannel): await close_cart_channel(interaction.channel, self.config, cart.customer_id)
        await interaction.response.send_message(f"Status atualizado: {CART_STATUS_LABELS.get(status, status)}.", ephemeral=True)

    def _get_cart_context(self, interaction):
        if not isinstance(interaction.channel, discord.TextChannel): return "Este botao precisa ser usado no canal do carrinho."
        cart = self.store.get_cart_by_channel(interaction.channel.id)
        if cart is None: return "Carrinho nao encontrado para este canal."
        panel = self.store.get_panel(cart.panel_id); option = self.store.get_option(cart.option_id)
        if panel is None or option is None: return "Produto do carrinho nao encontrado."
        return cart, panel, option


async def _send_auto_delivery(interaction, cart, option):
    if not option.delivery_content.strip(): return
    embed = discord.Embed(title="Entrega Automatica — Produto Entregue", description=f"<@{cart.customer_id}> seu produto **{option.label}** foi entregue!", colour=discord.Colour.green())
    embed.add_field(name="Conteudo da entrega", value=clip_text(option.delivery_content, 1024), inline=False)
    embed.set_footer(text="PRIMO Store — Obrigado pela preferencia!")
    await interaction.channel.send(embed=embed)


async def publish_or_update_panel(bot, config, store, panel_id):
    panel = store.get_panel(panel_id)
    if panel is None: raise SalesError(f"Painel {panel_id} nao encontrado.")
    opts = store.get_options(panel_id, True)
    if not opts: raise SalesError("Adicione ao menos uma opcao antes de publicar.")
    ch = bot.get_channel(panel.channel_id)
    if ch is None: ch = await bot.fetch_channel(panel.channel_id)
    if not isinstance(ch, discord.TextChannel): raise SalesError("Canal do painel nao encontrado ou nao e texto.")
    embed = build_panel_embed(panel, opts); view = SalesPanelView(store, panel.id)
    msg = None
    if panel.message_id is not None:
        try: msg = await ch.fetch_message(panel.message_id)
        except discord.NotFound: pass
    if msg is None: msg = await ch.send(embed=embed, view=view); store.mark_panel_published(panel.id, msg.id)
    else: await msg.edit(embed=embed, view=view)
    bot.add_view(SalesPanelView(store, panel.id), message_id=msg.id)
    return msg


def build_panel_embed(panel, opts):
    embed = discord.Embed(title=panel.title, description=panel.description, colour=discord.Colour(parse_color(panel.color)))
    if panel.thumbnail_url: embed.set_thumbnail(url=panel.thumbnail_url)
    if panel.image_url: embed.set_image(url=panel.image_url)
    for o in opts[:25]:
        vp = [f"Valor: **{o.price}**"]
        if o.description: vp.append(o.description)
        if o.details: vp.append(o.details)
        if o.delivery_content: vp.append("Entrega automatica ativada")
        embed.add_field(name=f"{o.label}", value=clip_text("\n".join(vp), 1024), inline=False)
    embed.set_footer(text=panel.footer or "PRIMO Store - Entrega rapida e suporte via ticket")
    return embed


def build_cart_embed(store, cart):
    panel = store.get_panel(cart.panel_id); option = store.get_option(cart.option_id); pix = store.get_pix()
    title = option.label if option else f"Produto {cart.option_id}"
    price = option.price if option else "Sob consulta"
    embed = discord.Embed(title=f"Carrinho #{cart.id}", description=f"Produto: **{title}**\nValor: **{price}**", colour=discord.Colour(parse_color(panel.color if panel else "#39FF14")))
    embed.add_field(name="Status", value=CART_STATUS_LABELS.get(cart.status, cart.status), inline=False)
    if option and option.details: embed.add_field(name="Detalhes", value=clip_text(option.details, 1024), inline=False)
    if cart.status in {"aguardando_pagamento", "aguardando_confirmacao"}:
        if pix is None: embed.add_field(name="PIX", value="PIX ainda nao configurado. Aguarde a staff configurar com `/pix_config`.", inline=False)
        else:
            embed.add_field(name="Chave PIX (copie abaixo facilmente)", value=f"```\n{pix.key}\n```", inline=False)
            if pix.qr_url: embed.set_image(url=pix.qr_url)
    elif option and option.image_url: embed.set_image(url=option.image_url)
    elif panel and panel.image_url: embed.set_image(url=panel.image_url)
    embed.set_footer(text="Envie o comprovante neste carrinho apos pagar.")
    return embed


async def create_cart_channel(*, guild, config, customer):
    cat = await ensure_category(guild, config.sales.carts_category_name, private_overwrites(guild, config))
    ow = private_overwrites(guild, config)
    ow[customer] = discord.PermissionOverwrite(view_channel=True, send_messages=True, read_message_history=True, attach_files=True, embed_links=True)
    return await guild.create_text_channel(name=f"carrinho-{slugify(customer.display_name)}", category=cat, overwrites=ow, topic=f"Carrinho de {customer} ({customer.id})", reason="PRIMO Store cart")


async def close_cart_channel(ch, config, cid):
    cat = await ensure_category(ch.guild, config.sales.closed_carts_category_name, private_overwrites(ch.guild, config))
    member = ch.guild.get_member(cid)
    ow = private_overwrites(ch.guild, config)
    if member is not None: ow[member] = discord.PermissionOverwrite(view_channel=False)
    await ch.edit(category=cat, overwrites=ow, reason="PRIMO Store cart closed")


async def ensure_category(guild, name, ow):
    cat = discord.utils.get(guild.categories, name=name)
    if cat is not None: await cat.edit(overwrites=ow); return cat
    return await guild.create_category(name=name, overwrites=ow)


def private_overwrites(guild, config):
    ow = {guild.default_role: discord.PermissionOverwrite(view_channel=False)}
    sr = staff_role_for(guild, config)
    if sr is not None: ow[sr] = discord.PermissionOverwrite(view_channel=True, send_messages=True, read_message_history=True, manage_messages=True)
    if guild.me is not None: ow[guild.me] = discord.PermissionOverwrite(view_channel=True, send_messages=True, read_message_history=True, manage_channels=True, manage_messages=True, attach_files=True, embed_links=True)
    return ow


async def log_sales_event(guild, config, msg):
    if guild is None: return
    ch = discord.utils.get(guild.text_channels, name=config.sales.logs_channel_name)
    if ch is not None: await ch.send(msg)


def is_staff(interaction, config):
    if not isinstance(interaction.user, discord.Member): return False
    if interaction.user.guild_permissions.manage_guild: return True
    sr = staff_role_for(interaction.guild, config) if interaction.guild else None
    return sr in interaction.user.roles if sr is not None else False


def staff_role_for(guild, config):
    rc = config.roles_by_key.get(config.sales.staff_role_key)
    rn = rc.name if rc else "Staff"
    return discord.utils.get(guild.roles, name=rn)


def attachment_or_url(att, url):
    if att is not None: return att.url
    return (url or "").strip()


def slugify(value):
    text = value.casefold(); text = re.sub(r"[^a-z0-9]+", "-", text); text = text.strip("-")
    return text[:32] or "cliente"


def clip_text(value, limit):
    text = value.strip()
    if len(text) <= limit: return text
    return text[:limit - 3].rstrip() + "..."
