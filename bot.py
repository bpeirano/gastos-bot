#!/usr/bin/env python3
"""
Bot de Telegram — Control de Gastos → Google Sheets
=====================================================
Formato de mensaje:
  <monto> <descripción> <cuenta>

  Ejemplos:
    15000 Starbucks SC
    32900 Supermercado Lider CTA
    8500 Almuerzo CMR

Cuentas:
  SC  = Santander Tarjeta Crédito
  CTA = Santander Cuenta Corriente
  CMR = Falabella CMR

Variables de entorno requeridas:
  BOT_TOKEN          — Token del bot de Telegram
  GOOGLE_CREDENTIALS — Contenido del JSON de la cuenta de servicio de Google
  SHEET_ID           — ID del Google Sheet (de la URL)
"""

import os
import re
import json
import logging
from datetime import datetime

import gspread
from google.oauth2.service_account import Credentials
from telegram import Update, ReplyKeyboardMarkup, ReplyKeyboardRemove
from telegram.ext import (
    Application, CommandHandler, MessageHandler,
    ContextTypes, filters, ConversationHandler
)

# ─── Logging ──────────────────────────────────────────────────────────────────
logging.basicConfig(
    format="%(asctime)s [%(levelname)s] %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# ─── Config ───────────────────────────────────────────────────────────────────
BOT_TOKEN   = os.environ.get("BOT_TOKEN", "8935559375:AAFbL-AOucO04Nf8B-yljgKMAO6PHDG_sXk")
SHEET_ID    = os.environ["SHEET_ID"]
GOOGLE_CREDS_JSON = os.environ["GOOGLE_CREDENTIALS"]

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]

# Estados de conversación
ESPERANDO_CATEGORIA = 1

# ─── Cuentas ──────────────────────────────────────────────────────────────────
CUENTAS = {
    "SC":  ("Santander",     "Tarjeta Crédito"),
    "CTA": ("Santander",     "Cuenta Corriente"),
    "CMR": ("Falabella CMR", "Tarjeta Crédito"),
}

CATEGORIAS = [
    "Supermercado", "Restaurante", "Café", "Transporte", "Entretenimiento",
    "Salud", "Educación", "Ropa", "Hogar", "Tecnología",
    "Viajes", "Retiro ATM", "Transferencia", "Otro"
]

# ─── Google Sheets ────────────────────────────────────────────────────────────

def get_sheet():
    creds_dict = json.loads(GOOGLE_CREDS_JSON)
    creds = Credentials.from_service_account_info(creds_dict, scopes=SCOPES)
    client = gspread.authorize(creds)
    sh = client.open_by_key(SHEET_ID)

    # Obtener o crear hoja "Gastos"
    try:
        ws = sh.worksheet("Gastos")
    except gspread.exceptions.WorksheetNotFound:
        ws = sh.add_worksheet(title="Gastos", rows=1000, cols=7)
        ws.append_row(["Fecha", "Descripción", "Monto", "Cuenta", "Tipo", "Categoría", "Notas"])
        # Formato encabezado
        ws.format("A1:G1", {
            "textFormat": {"bold": True},
            "backgroundColor": {"red": 0.2, "green": 0.2, "blue": 0.2}
        })
    return ws

def guardar_en_sheet(tx: dict) -> bool:
    try:
        ws = get_sheet()
        ws.append_row([
            tx["fecha"],
            tx["descripcion"],
            tx["monto"],
            tx["cuenta_label"],
            tx["tipo"],
            tx["categoria"],
            tx.get("notas", ""),
        ])
        return True
    except Exception as e:
        logger.error(f"Error escribiendo en Sheet: {e}")
        return False

# ─── Parseo de mensaje ────────────────────────────────────────────────────────

def parsear_monto(s: str) -> float:
    s = s.replace("$", "").replace("\xa0", "").replace(" ", "").strip()
    if "." in s and "," not in s and len(s.split(".")[-1]) >= 3:
        s = s.replace(".", "")          # 1.500 → 1500
    elif "," in s and "." in s:
        s = s.replace(".", "").replace(",", ".")
    elif "," in s:
        s = s.replace(",", ".")
    try:
        return float(s)
    except:
        return 0.0

def parsear_mensaje(texto: str) -> dict | None:
    texto = texto.strip()

    # Buscar código de cuenta
    m_cuenta = re.search(r'\b(SC|CTA|CMR)\b', texto, re.IGNORECASE)
    if not m_cuenta:
        return None
    cuenta_code = m_cuenta.group(1).upper()
    sin_cuenta = (texto[:m_cuenta.start()] + texto[m_cuenta.end():]).strip()

    # Buscar monto (primer número)
    m_monto = re.search(r'[\$]?([\d.,]+)', sin_cuenta)
    if not m_monto:
        return None
    monto = parsear_monto(m_monto.group(1))
    if monto <= 0:
        return None
    sin_monto = (sin_cuenta[:m_monto.start()] + sin_cuenta[m_monto.end():]).strip()

    # Resto = descripción
    descripcion = re.sub(r'\s+', ' ', sin_monto).strip() or "Sin descripción"

    banco, tipo = CUENTAS[cuenta_code]
    cuenta_label = {"SC": "Santander TC", "CTA": "Cta Corriente", "CMR": "Falabella CMR"}[cuenta_code]

    return {
        "fecha":       datetime.now().strftime("%Y-%m-%d"),
        "descripcion": descripcion.upper(),
        "monto":       monto,
        "cuenta_code": cuenta_code,
        "cuenta_label": cuenta_label,
        "banco":       banco,
        "tipo":        tipo,
    }

# ─── Categorización automática ────────────────────────────────────────────────

# Palabras clave → categoría
KEYWORDS = {
    "Supermercado":    ["LIDER", "JUMBO", "UNIMARC", "SANTA ISABEL", "WALMART", "TOTTUS", "ACUENTA", "SUPERMERCADO"],
    "Restaurante":     ["RESTAURANT", "RESTO", "SUSHI", "PIZZA", "BURGER", "MC DONALD", "MCDONALD", "SUBWAY", "KFC",
                        "DOMINOES", "DOMINOS", "CHILI", "NOODLE", "GRILL", "CANTINA", "PARRILLA", "COMIDA"],
    "Café":            ["STARBUCKS", "CAFE", "CAFÉ", "COFFEE", "JUAN VALDEZ", "DUNKIN", "TEALIVE"],
    "Transporte":      ["UBER", "CABIFY", "DIDI", "TAXI", "METRO", "BIP", "SHELL", "COPEC", "PETROBRAS",
                        "ESSO", "BENCINA", "GASOLINA", "ESTACIONAMIENTO", "PARKING", "EASY TAXI"],
    "Entretenimiento": ["CINEMA", "CINE", "NETFLIX", "SPOTIFY", "STEAM", "PLAYSTATION", "XBOX",
                        "DISNEY", "HBO", "PRIME", "YOUTUBE", "TWITCH", "APPLE TV", "TICKET"],
    "Salud":           ["FARMACIA", "CRUZ VERDE", "AHUMADA", "SALCOBRAND", "CLINICA", "CLÍNICA",
                        "MEDICO", "MÉDICO", "HOSPITAL", "DENTAL", "OPTICA", "ÓPTICA", "LAB"],
    "Educación":       ["UNIVERSIDAD", "COLEGIO", "INSTITUTO", "UDEMY", "COURSERA", "LIBRO", "LIBRERIA",
                        "LIBRERÍA", "AMAZON KINDLE", "DUOLINGO"],
    "Ropa":            ["ZARA", "H&M", "FALABELLA TIENDA", "RIPLEY", "PARIS", "NIKE", "ADIDAS",
                        "PUMA", "GAP", "FOREVER 21", "MANGO", "TOPSHOP"],
    "Hogar":           ["EASY", "HOMECENTER", "SODIMAC", "IKEA", "CORONA", "FERRETERIA", "FERRETERÍA",
                        "ELECTRICIDAD", "AGUA", "GAS", "INTERNET", "LUZ", "CLARO", "ENTEL", "MOVISTAR", "VTR"],
    "Tecnología":      ["APPLE", "SAMSUNG", "LG", "DELL", "HP", "LENOVO", "AMAZON", "MERCADOLIBRE",
                        "FALABELLA.COM", "RIPLEY.COM", "PCFACTORY", "ABCDIN"],
    "Viajes":          ["LATAM", "SKY", "HOTEL", "AIRBNB", "BOOKING", "DESPEGAR", "AEROPUERTO",
                        "HOSTAL", "AGENCIA", "VIAJE"],
    "Retiro ATM":      ["ATM", "CAJERO", "REDBANC"],
    "Transferencia":   ["TRANSFERENCIA", "TRANSFER"],
}

def categorizar(descripcion: str) -> str:
    desc = descripcion.upper()
    for categoria, keywords in KEYWORDS.items():
        for kw in keywords:
            if kw in desc:
                return categoria
    return "Otro"

# ─── Handlers del bot ─────────────────────────────────────────────────────────

# Estado temporal: chat_id → transacción guardada esperando categoría
pending: dict[int, dict] = {}

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "👋 ¡Hola! Soy tu bot de gastos.\n\n"
        "Escríbeme el gasto así:\n"
        "  *15000 Starbucks SC*\n"
        "  *32900 Lider CTA*\n"
        "  *8500 Almuerzo CMR*\n\n"
        "Cuentas disponibles:\n"
        "  SC = Santander Tarjeta Crédito\n"
        "  CTA = Santander Cuenta Corriente\n"
        "  CMR = Falabella CMR\n\n"
        "Cada gasto queda guardado en tu Google Sheet al instante.",
        parse_mode="Markdown"
    )

async def cmd_skip(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    if chat_id in pending:
        del pending[chat_id]
    await update.message.reply_text("👍 Ok, categoría dejada como 'Otro'.")

async def cmd_resumen(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Muestra un link al Google Sheet."""
    await update.message.reply_text(
        f"📊 Ver todos tus gastos:\n"
        f"https://docs.google.com/spreadsheets/d/{SHEET_ID}",
    )

async def manejar_foto(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "📸 Vi la imagen, pero no puedo leer el texto de pantallazos.\n\n"
        "Escríbeme el gasto directamente:\n"
        "  *15000 Starbucks SC*",
        parse_mode="Markdown"
    )

async def manejar_texto(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    texto = update.message.text.strip()

    # ── Corrección de categoría pendiente ─────────────────────────────────────
    if chat_id in pending:
        tx = pending[chat_id]
        texto_norm = texto.strip().title()

        # Buscar coincidencia en lista de categorías
        cat_match = next(
            (c for c in CATEGORIAS if c.lower() == texto.lower() or texto.lower() in c.lower()),
            None
        )

        if cat_match:
            tx["categoria"] = cat_match
            ok = guardar_en_sheet(tx)
            del pending[chat_id]
            if ok:
                await update.message.reply_text(
                    f"✅ *${tx['monto']:,.0f}* {tx['descripcion']}\n"
                    f"📂 {cat_match}  •  {tx['cuenta_label']}",
                    parse_mode="Markdown"
                )
            else:
                await update.message.reply_text("⚠️ No se pudo guardar en el Sheet. Intenta de nuevo.")
        else:
            kb = [[c] for c in CATEGORIAS]
            await update.message.reply_text(
                "Elige una categoría:",
                reply_markup=ReplyKeyboardMarkup(kb, one_time_keyboard=True, resize_keyboard=True)
            )
        return

    # ── Nuevo gasto ───────────────────────────────────────────────────────────
    tx = parsear_mensaje(texto)

    if not tx:
        await update.message.reply_text(
            "❓ No entendí. Formato: *monto descripción cuenta*\n"
            "Ejemplo: *15000 Starbucks SC*\n\n"
            "Cuentas: SC / CTA / CMR",
            parse_mode="Markdown"
        )
        return

    categoria = categorizar(tx["descripcion"])
    tx["categoria"] = categoria

    if categoria != "Otro":
        # Categoría conocida → guardar de inmediato sin preguntar
        ok = guardar_en_sheet(tx)
        emoji = {"Santander": "🔴", "Falabella CMR": "🟡"}.get(tx["banco"], "🏦")
        if ok:
            await update.message.reply_text(
                f"✅ *${tx['monto']:,.0f}* {tx['descripcion']}\n"
                f"{emoji} {tx['cuenta_label']}  •  📂 {categoria}",
                parse_mode="Markdown"
            )
        else:
            await update.message.reply_text("⚠️ Error al guardar en Google Sheets. Intenta de nuevo.")
    else:
        # Categoría desconocida → guardar y preguntar
        ok = guardar_en_sheet(tx)
        if not ok:
            await update.message.reply_text("⚠️ Error al guardar en Google Sheets. Intenta de nuevo.")
            return

        pending[chat_id] = tx
        kb = [[c] for c in CATEGORIAS]
        emoji = {"Santander": "🔴", "Falabella CMR": "🟡"}.get(tx["banco"], "🏦")
        await update.message.reply_text(
            f"✅ *${tx['monto']:,.0f}* {tx['descripcion']} guardado.\n"
            f"{emoji} {tx['cuenta_label']}\n\n"
            f"¿Qué categoría es? (o /skip)",
            parse_mode="Markdown",
            reply_markup=ReplyKeyboardMarkup(kb, one_time_keyboard=True, resize_keyboard=True)
        )

# ─── Main ─────────────────────────────────────────────────────────────────────

def main():
    app = Application.builder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start",   cmd_start))
    app.add_handler(CommandHandler("skip",    cmd_skip))
    app.add_handler(CommandHandler("resumen", cmd_resumen))
    app.add_handler(MessageHandler(filters.PHOTO, manejar_foto))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, manejar_texto))

    logger.info("Bot iniciado. Esperando mensajes...")
    app.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()
