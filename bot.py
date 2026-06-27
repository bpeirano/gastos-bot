#!/usr/bin/env python3
import os, re, json, logging
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
SCOPES = ["https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive"]

MESES = {"enero":1,"febrero":2,"marzo":3,"abril":4,"mayo":5,"junio":6,"julio":7,"agosto":8,"septiembre":9,"octubre":10,"noviembre":11,"diciembre":12,"ene":1,"feb":2,"mar":3,"abr":4,"may":5,"jun":6,"jul":7,"ago":8,"sep":9,"oct":10,"nov":11,"dic":12}

def get_sheet():
    creds = Credentials.from_service_account_info(json.loads(GOOGLE_CREDS_JSON), scopes=SCOPES)
    sh = gspread.authorize(creds).open_by_key(SHEET_ID)
    try:
        return sh.worksheet("Gastos")
    except gspread.exceptions.WorksheetNotFound:
        ws = sh.add_worksheet(title="Gastos", rows=1000, cols=5)
        ws.append_row(["Fecha","Descripcion","Monto","Categoria","Notas"])
        ws.format("A1:E1", {"textFormat": {"bold": True}})
        return ws

def guardar_en_sheet(tx):
    try:
        get_sheet().append_row([tx["fecha"], tx["descripcion"], tx["monto"], tx["categoria"], tx.get("notas","")])
        return True
    except Exception as e:
        logger.error(f"Error: {e}")
        return False

def parsear_fecha(texto):
    texto = texto.strip().lower()
    hoy = datetime.now()
    if texto in ("hoy", ""): return hoy.strftime("%Y-%m-%d")
    if texto == "ayer": return (hoy - timedelta(days=1)).strftime("%Y-%m-%d")
    if texto == "anteayer": return (hoy - timedelta(days=2)).strftime("%Y-%m-%d")
    m = re.match(r"(\d{1,2})\s+([a-z]+)", texto)
    if m:
        mes = MESES.get(m.group(2))
        if mes:
            try: return datetime(hoy.year, mes, int(m.group(1))).strftime("%Y-%m-%d")
            except: pass
    m = re.match(r"(\d{1,2})[/\-](\d{1,2})", texto)
    if m:
        try: return datetime(hoy.year, int(m.group(2)), int(m.group(1))).strftime("%Y-%m-%d")
        except: pass
    return hoy.strftime("%Y-%m-%d")

def parsear_monto(s):
    s = s.replace("$","").replace(" ","").strip()
    if "." in s and "," not in s and len(s.split(".")[-1]) >= 3: s = s.replace(".","")
    elif "," in s and "." in s: s = s.replace(".","").replace(",",".")
    elif "," in s: s = s.replace(",",".")
    try: return float(s)
    except: return 0.0

def parsear_mensaje(texto):
    partes = re.split(r"\.\s+", texto.strip(), maxsplit=2)
    if len(partes) < 3: return None
    monto = parsear_monto(partes[1])
    if monto <= 0: return None
    if "," in partes[2]:
        p2 = partes[2].split(",", 1)
        fecha_str, categoria = p2[0].strip(), p2[1].strip().title()
    else:
        fecha_str, categoria = partes[2], "Sin categoria"
    return {"fecha": parsear_fecha(fecha_str), "descripcion": partes[0].strip().upper(), "monto": monto, "categoria": categoria}

async def cmd_start(update, context):
    await update.message.reply_text("Hola! Formato:\nconcepto. monto. fecha, categoria\n\nEjemplos:\ncafe. 5000. 15 junio, alimentos\nnetflix. 15000. hoy, entretenimiento\n\n/resumen - ver tu sheet")

async def cmd_resumen(update, context):
    await update.message.reply_text("Ver tus gastos:\nhttps://docs.google.com/spreadsheets/d/" + SHEET_ID)

async def manejar_foto(update, context):
    await update.message.reply_text("No puedo leer imagenes. Escribeme: cafe. 5000. hoy, alimentos")

async def manejar_texto(update, context):
    tx = parsear_mensaje(update.message.text.strip())
    if not tx:
        await update.message.reply_text("No entendi. Formato:\nconcepto. monto. fecha, categoria\nEjemplo: cafe. 5000. 15 junio, alimentos")
        return
    if guardar_en_sheet(tx):
        await update.message.reply_text(f"Guardado!\n{tx['descripcion']}\nMonto: ${tx['monto']:,.0f}\nFecha: {tx['fecha']}\nCategoria: {tx['categoria']}")
    else:
        await update.message.reply_text("Error al guardar. Intenta de nuevo.")

def main():
    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("resumen", cmd_resumen))
    app.add_handler(MessageHandler(filters.PHOTO, manejar_foto))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, manejar_texto))
    logger.info("Bot iniciado.")
    app.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()
