#!/usr/bin/env python3
"""
Bot de Telegram — Control de Gastos → Google Sheets
=====================================================
Formato:  monto. concepto. fecha. categoria

Ejemplos:
  5000. cafe. 15 junio. alimentos
  15000. netflix. hoy. entretenimiento
  32000. supermercado. ayer. alimentos
  8500. almuerzo. hoy. restaurante

Fechas soportadas: hoy, ayer, anteayer, 15 junio, 15/6

Variables de entorno requeridas:
  BOT_TOKEN          - Token del bot de Telegram
  GOOGLE_CREDENTIALS - Contenido JSON de la cuenta de servicio de Google
  SHEET_ID           - ID del Google Sheet
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

logging.basicConfig(format="%(asctime)s [%(levelname)s] %(message)s", level=logging.INFO)
logger = logging.getLogger(__name__)

BOT_TOKEN = os.environ.get("BOT_TOKEN", "8935559375:AAFbL-AOucO04Nf8B-yljgKMAO6PHDG_sXk")
SHEET_ID  = os.environ["SHEET_ID"]
GOOGLE_CREDS_JSON = os.environ["GOOGLE_CREDENTIALS"]

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]

MESES = {
    "enero": 1, "febrero": 2, "marzo": 3, "abril": 4,
    "mayo": 5, "junio": 6, "julio": 7, "agosto": 8,
    "septiembre": 9, "octubre": 10, "noviembre": 11, "diciembre": 12,
    "ene": 1, "feb": 2, "mar": 3, "abr": 4, "may": 5, "jun": 6,
    "jul": 7, "ago": 8, "sep": 9, "oct": 10, "nov": 11, "dic": 12,
}


def get_sheet():
    creds = Credentials.from_service_account_info(json.loads(GOOGLE_CREDS_JSON), scopes=SCOPES)
    sh = gspread.authorize(creds).open_by_key(SHEET_ID)
    try:
        return sh.worksheet("Gastos")
    except gspread.exceptions.WorksheetNotFound:
        ws = sh.add_worksheet(title="Gastos", rows=1000, cols=5)
        ws.append_row(["Fecha", "Descripcion", "Monto", "Categoria", "Notas"])
        ws.format("A1:E1", {"textFormat": {"bold": True}})
        return ws


def guardar_en_sheet(tx):
    try:
        get_sheet().append_row([
            tx["fecha"], tx["descripcion"], tx["monto"], tx["categoria"], tx.get("notas", "")
        ])
        return True
    except Exception as e:
        logger.error(f"Error: {e}")
        return False


def parsear_fecha(texto):
    texto = texto.strip().lower()
    hoy = datetime.now()
    if texto in ("hoy", ""):
        return hoy.strftime("%Y-%m-%d")
    if texto == "ayer":
        return (hoy - timedelta(days=1)).strftime("%Y-%m-%d")
    if texto == "anteayer":
        return (hoy - timedelta(days=2)).strftime("%Y-%m-%d")
    # "15 junio" / "15 jun"
    m = re.match(r"(\d{1,2})\s+([a-z]+)", texto)
    if m:
        mes = MESES.get(m.group(2))
        if mes:
            try:
                return datetime(hoy.year, mes, int(m.group(1))).strftime("%Y-%m-%d")
            except ValueError:
                pass
    # "15/6" o "15-6"
    m = re.match(r"(\d{1,2})[/\-](\d{1,2})", texto)
    if m:
        try:
            return datetime(hoy.year, int(m.group(2)), int(m.group(1))).strftime("%Y-%m-%d")
        except ValueError:
            pass
    return hoy.strftime("%Y-%m-%d")


def parsear_monto(s):
    s = s.replace("$", "").replace(" ", "").strip()
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


def parsear_mensaje(texto):
    """
    Formato: monto. concepto. fecha. categoria

    Ejemplos:
      5000. cafe. 15 junio. alimentos
      15000. netflix. hoy. entretenimiento
      32000. supermercado. ayer. alimentos
    """
    texto = texto.strip()
    # Separar por ". " — necesitamos exactamente 4 partes
    partes = re.split(r"\.\s+", texto, maxsplit=3)

    if len(partes) < 4:
        return None

    monto     = parsear_monto(partes[0])
    concepto  = partes[1].strip().upper()
    fecha     = parsear_fecha(partes[2].strip())
    categoria = partes[3].strip().title()

    if monto <= 0:
        return None

    return {
        "fecha":       fecha,
        "descripcion": concepto or "SIN DESCRIPCION",
        "monto":       monto,
        "categoria":   categoria,
    }


async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Hola! Soy tu bot de gastos.\n\n"
        "Formato:\n"
        "  monto. concepto. fecha. categoria\n\n"
        "Ejemplos:\n"
        "  5000. cafe. 15 junio. alimentos\n"
        "  15000. netflix. hoy. entretenimiento\n"
        "  32000. supermercado. ayer. alimentos\n"
        "  8500. almuerzo. 28 jun. restaurante\n\n"
        "Fechas: hoy, ayer, 15 junio, 15/6\n"
        "/resumen - ver tu Google Sheet"
    )


async def cmd_resumen(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Ver todos tus gastos:\n"
        "https://docs.google.com/spreadsheets/d/" + SHEET_ID
    )


async def manejar_foto(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "No puedo leer imagenes. Escribeme:\n"
        "5000. cafe. 15 junio. alimentos"
    )


async def manejar_texto(update: Update, context: ContextTypes.DEFAULT_TYPE):
    tx = parsear_mensaje(update.message.text.strip())
    if not tx:
        await update.message.reply_text(
            "No entendi. Formato:\n"
            "monto. concepto. fecha. categoria\n\n"
            "Ejemplo: 5000. cafe. 15 junio. alimentos"
        )
        return
    if guardar_en_sheet(tx):
        await update.message.reply_text(
            "Guardado!\n"
            + tx["descripcion"] + "\n"
            + "Monto: $" + "{:,.0f}".format(tx["monto"]) + "\n"
            + "Fecha: " + tx["fecha"] + "\n"
            + "Categoria: " + tx["categoria"]
        )
    else:
        await update.message.reply_text("Error al guardar. Intenta de nuevo.")


def main():
    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start",   cmd_start))
    app.add_handler(CommandHandler("resumen", cmd_resumen))
    app.add_handler(MessageHandler(filters.PHOTO, manejar_foto))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, manejar_texto))
    logger.info("Bot iniciado.")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
