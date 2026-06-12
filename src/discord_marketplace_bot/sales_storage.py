from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from discord_marketplace_bot.config import PROHIBITED_CATALOG_TERMS

SALES_PROHIBITED_TERMS = (
    "nitro link", "n1tr0", "l1nk nitro", "conta nitrada", "n1trad",
    "token", "selfbot", "self-bot", "clonag", "cl0nag", "spoofer", "cheat", "bypass",
)

MAX_PANEL_OPTIONS = 25
MAX_DELIVERY_LENGTH = 4000


class SalesError(ValueError):
    """Raised when sales data is invalid or cannot be processed."""


@dataclass(frozen=True)
class SalesPanel:
    id: int; guild_id: int; channel_id: int; title: str; description: str
    image_url: str; thumbnail_url: str; footer: str; color: str; active: bool
    message_id: int | None


@dataclass(frozen=True)
class SalesOption:
    id: int; panel_id: int; label: str; description: str; price: str
    details: str; image_url: str; delivery_content: str; active: bool


@dataclass(frozen=True)
class Cart:
    id: int; guild_id: int; channel_id: int; customer_id: int
    panel_id: int; option_id: int; status: str; log_message_id: int | None


@dataclass(frozen=True)
class PixConfig:
    key: str; qr_url: str


@dataclass(frozen=True)
class BotConfig:
    custom_commands: str; webhook_url: str; auto_delivery_enabled: str


class SalesStore:
    def __init__(self, path):
        self.path = Path(path); self.path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(self.path); self.conn.row_factory = sqlite3.Row
        self.initialize()

    def initialize(self):
        self.conn.executescript("""PRAGMA foreign_keys = ON;
            CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS sales_panels (
                id INTEGER PRIMARY KEY AUTOINCREMENT, guild_id INTEGER NOT NULL, channel_id INTEGER NOT NULL,
                title TEXT NOT NULL, description TEXT NOT NULL, image_url TEXT NOT NULL DEFAULT '',
                thumbnail_url TEXT NOT NULL DEFAULT '', footer TEXT NOT NULL DEFAULT '',
                color TEXT NOT NULL DEFAULT '#39FF14', active INTEGER NOT NULL DEFAULT 1,
                message_id INTEGER, created_by INTEGER NOT NULL,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);
            CREATE TABLE IF NOT EXISTS sales_options (
                id INTEGER PRIMARY KEY AUTOINCREMENT, panel_id INTEGER NOT NULL REFERENCES sales_panels(id) ON DELETE CASCADE,
                label TEXT NOT NULL, description TEXT NOT NULL, price TEXT NOT NULL,
                details TEXT NOT NULL DEFAULT '', image_url TEXT NOT NULL DEFAULT '',
                delivery_content TEXT NOT NULL DEFAULT '', active INTEGER NOT NULL DEFAULT 1,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);
            CREATE TABLE IF NOT EXISTS carts (
                id INTEGER PRIMARY KEY AUTOINCREMENT, guild_id INTEGER NOT NULL, channel_id INTEGER NOT NULL UNIQUE,
                customer_id INTEGER NOT NULL, panel_id INTEGER NOT NULL REFERENCES sales_panels(id),
                option_id INTEGER NOT NULL REFERENCES sales_options(id), status TEXT NOT NULL,
                log_message_id INTEGER, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);""")
        try: self.conn.execute("ALTER TABLE sales_options ADD COLUMN delivery_content TEXT NOT NULL DEFAULT ''")
        except sqlite3.OperationalError: pass
        try: self.conn.execute("ALTER TABLE carts RENAME COLUMN message_id TO log_message_id")
        except sqlite3.OperationalError: pass
        self.conn.commit()

    def close(self): self.conn.close()
    def set_setting(self, key, value):
        self.conn.execute("INSERT INTO settings (key,value) VALUES (?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (key, value.strip())); self.conn.commit()
    def get_setting(self, key):
        row = self.conn.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
        return str(row["value"]) if row else ""
    def set_pix(self, key, qr_url):
        if not key.strip(): raise SalesError("A chave PIX nao pode ficar vazia.")
        self.set_setting("pix_key", key); self.set_setting("pix_qr_url", qr_url)
    def get_pix(self):
        key = self.get_setting("pix_key")
        return PixConfig(key=key, qr_url=self.get_setting("pix_qr_url")) if key else None
    def set_bot_config(self, *, custom_commands="", webhook_url="", auto_delivery_enabled=True):
        self.set_setting("custom_commands", custom_commands.strip())
        self.set_setting("webhook_url", webhook_url.strip())
        self.set_setting("auto_delivery_enabled", "1" if auto_delivery_enabled else "0")
    def get_bot_config(self):
        return BotConfig(custom_commands=self.get_setting("custom_commands"), webhook_url=self.get_setting("webhook_url"), auto_delivery_enabled=self.get_setting("auto_delivery_enabled"))
    def create_panel(self, *, guild_id, channel_id, title, description, image_url="", thumbnail_url="", footer="", color="#39FF14", created_by):
        ensure_safe_sales_text(title, description, footer)
        c = self.conn.execute("INSERT INTO sales_panels (guild_id,channel_id,title,description,image_url,thumbnail_url,footer,color,created_by) VALUES (?,?,?,?,?,?,?,?,?)", (guild_id, channel_id, title.strip(), description.strip(), image_url.strip(), thumbnail_url.strip(), footer.strip(), color.strip() or "#39FF14", created_by))
        self.conn.commit(); p = self.get_panel(c.lastrowid)
        if p is None: raise SalesError("Painel criado, mas nao foi possivel recarregar."); return p
    def add_option(self, *, panel_id, label, description, price, details="", image_url="", delivery_content=""):
        panel = self.get_panel(panel_id)
        if panel is None: raise SalesError(f"Painel {panel_id} nao encontrado.")
        if len(self.get_options(panel_id, True)) >= MAX_PANEL_OPTIONS: raise SalesError(f"Maximo {MAX_PANEL_OPTIONS} opcoes.")
        ensure_safe_sales_text(label, description, price, details, delivery_content)
        c = self.conn.execute("INSERT INTO sales_options (panel_id,label,description,price,details,image_url,delivery_content) VALUES (?,?,?,?,?,?,?)", (panel_id, label.strip(), description.strip(), price.strip(), details.strip(), image_url.strip(), delivery_content.strip()))
        self.conn.commit(); o = self.get_option(c.lastrowid)
        if o is None: raise SalesError("Opcao criada, mas nao foi possivel recarregar."); return o
    def get_panel(self, pid):
        r = self.conn.execute("SELECT * FROM sales_panels WHERE id=?", (pid,)).fetchone(); return _panel_from_row(r) if r else None
    def list_panels(self, guild_id=None, active_only=False):
        q = "SELECT * FROM sales_panels"; params = []; clauses = []
        if guild_id is not None: clauses.append("guild_id=?"); params.append(guild_id)
        if active_only: clauses.append("active=1")
        if clauses: q += " WHERE " + " AND ".join(clauses)
        q += " ORDER BY id DESC"; return [_panel_from_row(r) for r in self.conn.execute(q, params).fetchall()]
    def list_published_panels(self, guild_id=None):
        return [p for p in self.list_panels(guild_id, True) if p.message_id is not None]
    def get_options(self, panel_id, active_only=False):
        q = "SELECT * FROM sales_options WHERE panel_id=?"; params = [panel_id]
        if active_only: q += " AND active=1"
        q += " ORDER BY id"; return [_option_from_row(r) for r in self.conn.execute(q, params).fetchall()]
    def get_option(self, oid):
        r = self.conn.execute("SELECT * FROM sales_options WHERE id=?", (oid,)).fetchone(); return _option_from_row(r) if r else None
    def mark_panel_published(self, pid, mid):
        self.conn.execute("UPDATE sales_panels SET message_id=?, updated_at=CURRENT_TIMESTAMP WHERE id=?", (mid, pid)); self.conn.commit()
    def set_panel_active(self, pid, active):
        self.conn.execute("UPDATE sales_panels SET active=?, updated_at=CURRENT_TIMESTAMP WHERE id=?", (1 if active else 0, pid)); self.conn.commit()
    def create_cart(self, *, guild_id, channel_id, customer_id, panel_id, option_id, status="aberto"):
        c = self.conn.execute("INSERT INTO carts (guild_id,channel_id,customer_id,panel_id,option_id,status) VALUES (?,?,?,?,?,?)", (guild_id, channel_id, customer_id, panel_id, option_id, status))
        self.conn.commit(); cart = self.get_cart(c.lastrowid)
        if cart is None: raise SalesError("Carrinho criado, mas nao foi possivel recarregar."); return cart
    def get_cart(self, cid):
        r = self.conn.execute("SELECT * FROM carts WHERE id=?", (cid,)).fetchone(); return _cart_from_row(r) if r else None
    def get_cart_by_channel(self, chid):
        r = self.conn.execute("SELECT * FROM carts WHERE channel_id=?", (chid,)).fetchone(); return _cart_from_row(r) if r else None
    def list_open_carts(self, guild_id=None):
        terminal = ("cancelado", "entregue", "fechado")
        q = "SELECT * FROM carts WHERE status NOT IN (?,?,?)"; params = list(terminal)
        if guild_id is not None: q += " AND guild_id=?"; params.append(guild_id)
        q += " ORDER BY id DESC"; return [_cart_from_row(r) for r in self.conn.execute(q, params).fetchall()]
    def set_cart_log_message(self, cid, lmid):
        self.conn.execute("UPDATE carts SET log_message_id=?, updated_at=CURRENT_TIMESTAMP WHERE id=?", (lmid, cid)); self.conn.commit()
    def update_cart_status(self, cid, status):
        self.conn.execute("UPDATE carts SET status=?, updated_at=CURRENT_TIMESTAMP WHERE id=?", (status, cid)); self.conn.commit()


def ensure_safe_sales_text(*chunks):
    text = " ".join(c for c in chunks if c).casefold()
    blocked = [t for t in (*PROHIBITED_CATALOG_TERMS, *SALES_PROHIBITED_TERMS) if t in text]
    if blocked: raise SalesError(f"Texto contem termo bloqueado: {', '.join(sorted(set(blocked)))}")

def _panel_from_row(r):
    return SalesPanel(id=int(r["id"]), guild_id=int(r["guild_id"]), channel_id=int(r["channel_id"]), title=str(r["title"]), description=str(r["description"]), image_url=str(r["image_url"] or ""), thumbnail_url=str(r["thumbnail_url"] or ""), footer=str(r["footer"] or ""), color=str(r["color"] or "#39FF14"), active=bool(r["active"]), message_id=int(r["message_id"]) if r["message_id"] is not None else None)

def _option_from_row(r):
    dc = str(r["delivery_content"] or "") if "delivery_content" in r.keys() else ""
    return SalesOption(id=int(r["id"]), panel_id=int(r["panel_id"]), label=str(r["label"]), description=str(r["description"]), price=str(r["price"]), details=str(r["details"] or ""), image_url=str(r["image_url"] or ""), delivery_content=dc, active=bool(r["active"]))

def _cart_from_row(r):
    lm = None
    if "log_message_id" in r.keys(): lm = int(r["log_message_id"]) if r["log_message_id"] is not None else None
    elif "message_id" in r.keys(): lm = int(r["message_id"]) if r["message_id"] is not None else None
    return Cart(id=int(r["id"]), guild_id=int(r["guild_id"]), channel_id=int(r["channel_id"]), customer_id=int(r["customer_id"]), panel_id=int(r["panel_id"]), option_id=int(r["option_id"]), status=str(r["status"]), log_message_id=lm)
