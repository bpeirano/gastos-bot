#!/usr/bin/env python3
"""
Bot de Telegram — Control de Gastos → Google Sheets
=====================================================
Formato:  concepto. monto. fecha, categoria

Ejemplos:
  cafe. 5000. 15 junio, alimentos
  netflix. 15000. hoy, entretenimiento
  supermercado. 32000. ayer, alimentos
  almuerzo. 8500. hoy, restaurante

Fechas soportadas: hoy, ayer, anteayer, 15 junio, 15/6

Variables de entorno requeridas:
  BOT_TOKEN          — Token del bot de Telegram
  GOOGLE_CREDENTIALS — Contenido JSON de la cuenta de servicio de Google
  SHEET_ID           — ID del Google Sheet
"""

import os
import re
import json
import logging
from datetime import datetime, timedelta

import gspread
from google.oauth2.service_account import Credentials
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, ContextTypes, filters

# ─── Logging ──────────────────────────────────────────────────────────────────
logging.basicConfig(
    format="%(asctime)s [%(levelname)s] %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# ─── Config ───────────────────────────────────────────────────────────────────
BOT_TOKEN = os.environ.get("BOT_TOKEN", "8935559375:AAFbL-AOucO04Nf8B-yljgKMAO6PHDG_sXk")
SHEET_ID  = os.environ["SHEET_ID"]
GOOGLE_CREDS_JSON = os.environ["GOOGLE_CREDENTIALS"]

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]

# ─── Meses en español ─────────────────────────────────────────────────────────
MESES = {
    "enero": 1, "febrero": 2, "marzo": 3, "abril": 4,
    "mayo": 5, "junio": 6, "julio": 7, "agosto": 8,
    "septiembre": 9, "octubre": 10, "noviembre": 11, "diciembre": 12,
    "ene": 1, "feb": 2, "mar": 3, "abr": 4, "may": 5, "jun": 6,
    "jul": 7, "ago": 8, "sep": 9, "oct": 10, "nov": 11, "dic": 12,
}

# ─── Google Sheets ────────────────────────────────────────────────────────────

def get_sheet():
    creds_dict = json.loads(GOOGLE_CREDS_JSON)
    creds = Credentials.from_service_account_info(creds_dict, scopes=SCOPES)
    client = gspread.authorize(creds)
    sh = client.open_by_key(SHEET_ID)
    try:
        ws = sh.worksheet("Gastos")
    except gspread.exceptions.WorksheetNotFound:
        ws = sh.add_worksheet(title="Gastos", rows=1000, cols=5)
        ws.append_row(["Fecha", "Descripción", "Monto", "Categoría", "Notas"])
        ws.format("A1:E1", {"textFormat": {"bold": True}})
    return ws

def guardar_en_sheet(tx: dict) -> bool:
    try:
        ws = get_sheet()
        ws.append_row([
            tx["fecha"],
            tx["descripcion"],
            tx["monto"],
            tx["categoria"],
            tx.get("notas", ""),
        ])
        return True
    except Exception as e:
        logger.error(f"Error escribiendo en Sheet: {e}")
        return False

# ─── Parseo de fecha ──────────────────────────────────────────────────────────

def parsear_fecha(texto: str) -> str:
    texto = texto.strip().lower()
    hoy = datetime.now()

    if texto in ("hoy", ""):
        return hoy.strftime("%Y-%m-%d")
    if texto == "ayer":
        return (hoy - timedelta(days=1)).strftime("%Y-%m-%d")
    if texto == "anteayer":
        return (hoy - timedelta(days=2)).strftime("%Y-%m-%d")

    # "15 junio" / "15 jun"
    m = re.match(r'(\d{1,2})\s+([a-záéíóúü]+)', texto)
    if m:
        dia = int(m.group(1))
        mes = MESES.get(m.group(2))
        if mes:
            try:
                return datetime(hoy.year, mes, dia).strftime("%Y-%m-%d")
            except ValueError:
                pass

    # "15/6" / "15-6"
    m = re.match(r'(\d{1,2})[/\-](\d{1,2})', texto)
    if m:
        dia, mes = int(m.group(1)), int(m.group(2))
        try:
            return datetime(hoy.year, mes, dia).strftime("%Y-%m-%d")
        except ValueError:
            pass

    return hoy.strftime("%Y-%m-%d")

# ─── Parseo de monto ──────────────────────────────────────────────────────────

def parsear_monto(s: str) -> float:
    s = s.replace("$", "").replace("\xa0", "").replace(" ", "").strip()
    if "." in s and "," not in s and len(s.split(".")[-1]) >= 3:
        s = s.replace(".", "")
    elif "," in s and "." in s:
        s = s.replace(".", "").replace(",", ".")
    elif "," in s:
        s = s.replace(",", ".")
    try:
        return float(s)
    except Exception:
        return 0.0

# ─── Parseo principal ─────────────────────────────────────────────────────────

def parsear_mensaje(texto: str) -> dict | None:
    """
    Formato: concepto. monto. fecha, categoria

    Ejemplos:
      cafe. 5000. 15 junio, alimentos
      netflix. 15000. hoy, entretenimiento
      supermercado. 32000. ayer, alimentos
    """
    texto = texto.strip()

    # Dividir por ". " en hasta 3 partes: [concepto, monto_str, fecha_cat]
    partes = re.split(r'\.\s+', texto, maxsplit=2)

    if len(partes) < 3:
        return None

    concepto   = partes[0].strip().upper()
    monto_str  = partes[1].strip()
    fecha_cat  = partes[2].strip()

    # Parsear monto
    monto = parsear_monto(monto_str)
    if monto <= 0:
        return None

    # Dividir fecha_cat por ", "
    if "," in fecha_cat:
        partes2  = fecha_cat.split(",", 1)
        fecha_str = partes2[0].strip()
        categoria = partes2[1].strip().title()
    else:
        fecha_str = fecha_cat
        categoria = "Sin categoría"

    fecha = parsear_fecha(fecha_str)

    return {
        "fecha":       fecha,
        "descripcion": concepto or "SIN DESCRIPCIÓN",
        "monto":       monto,
        "categoria":   categoria,
    }

# ─── Handlers ─────────────────────────────────────────────────────────────────

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "👋 ¡Hola! Soy tu bot de gastos.\n\n"
        "Formato:\n"
        "  *concepto. monto. fecha, categoria*\n\n"
        "Ejemplos:\n"
        "  `cafe. 5000. 15 junio, alimentos`\n"
        "  `netflix. 15000. hoy, entretenimiento`\n"
        "  `supermercado. 32000. ayer, alimentos`\n"
        "  `almuerzo. 8500. 28 jun, restaurante`\n\n"
        "Fechas: *hoy*, *ayer*, *15 junio*, *15/6*\n"
        "/resumen — ver tu Google Sheet",
        parse_mode="Markdown"
    )

async def cmd_resumen(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        f"📊 Ver todos tus gastos:\n"
        f"https://docs.google.com/spreadsheets/d/{SHEET_ID}"
    )

async def manejar_foto(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "📸 No puedo leer imágenes. Escríbeme el gasto:\n"
        "`cafe. 5000. 15 junio, alimentos`",
        parse_mode="Markdown"
    )

async def manejar_texto(update: Update, context: ContextTypes.DEFAULT_TYPE):
    texto = update.message.text.strip()
    tx = parsear_mensaje(texto)

    if not tx:
        await update.message.reply_text(
            "❓ No entendí. Formato:\n"
            "*concepto. monto. fecha, categoria*\n\n"
            "Ejemplo: `cafe. 5000. 15 junio, alimentos`",
            parse_mode="Markdown"
        )
        return

    ok = guardar_en_sheet(tx)
    if ok:
        await update.message.reply_text(
            f"✅ *{tx['descripcion']}*\n"
            f"  💰 ${tx['monto']:,.0f}\n"
            f"  📅 {tx['fecha']}\n"
            f"  📂 {tx['categoria']}",
            parse_mode="Markdown"
        )
    else:
        await update.message.reply_text("⚠️ Error al guardar. Intenta de nuevo.")

# ─── Main ─────────────────────────────────────────────────────────────────────

def main():
    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start",   cmd_start))
    app.add_handler(CommandHandler("resumen", cmd_resumen))
    app.add_handler(MessageHandler(filters.PHOTO, manejar_foto))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, manejar_texto))
    logger.info("Bot iniciado. Esperando mensajes...")
    app.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()
