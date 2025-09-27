import os
import logging
import sqlite3
from datetime import datetime
from dotenv import load_dotenv

from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler,
    ConversationHandler, MessageHandler, filters, ContextTypes
)

# --- Config ---
logging.basicConfig(level=logging.INFO)
load_dotenv()
TOKEN = os.getenv("BOT_TOKEN")
if not TOKEN:
    raise SystemExit("Falta BOT_TOKEN en .env")

# --- DB ---
conn = sqlite3.connect("pacientes.db", check_same_thread=False)
c = conn.cursor()
c.execute("""
CREATE TABLE IF NOT EXISTS sesiones (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    nombre TEXT,
    tipo TEXT,
    pago INTEGER,
    fecha TEXT
)
""")
conn.commit()

# --- Estados ---
NOMBRE, TIPO, PAGO = range(3)

# --- Handlers ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        [InlineKeyboardButton("➕ Registrar sesión", callback_data="registrar")],
        [InlineKeyboardButton("📋 Listar últimos", callback_data="listar")],
        [InlineKeyboardButton("📊 Reporte mensual", callback_data="reporte_mes")]
    ]
    await update.message.reply_text("Hola! ¿Qué querés hacer?", reply_markup=InlineKeyboardMarkup(keyboard))

# menú general (botones)
async def menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if query.data == "registrar":
        await query.message.reply_text("📌 Escribí el *nombre del paciente*:", parse_mode="Markdown")
        return NOMBRE
    if query.data == "listar":
        c.execute("SELECT nombre, tipo, pago, fecha FROM sesiones ORDER BY fecha DESC LIMIT 10")
        rows = c.fetchall()
        texto = "\n".join([f"{r[0]} | {r[1]} | {'✅' if r[2] else '❌'} | {r[3]}" for r in rows]) or "No hay registros."
        await query.edit_message_text(texto)
        return ConversationHandler.END
    if query.data == "reporte_mes":
        await query.message.reply_text("Usá: /reporte YYYY-MM (ej: /reporte 2025-09)")
        return ConversationHandler.END

# Nombre (texto)
async def get_nombre(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["nombre"] = update.message.text.strip()
    keyboard = [
        [InlineKeyboardButton("👤 Particular", callback_data="particular")],
        [InlineKeyboardButton("🏥 Obra Social", callback_data="obra_social")]
    ]
    await update.message.reply_text("Seleccioná el tipo de paciente:", reply_markup=InlineKeyboardMarkup(keyboard))
    return TIPO

# Tipo (botón)
async def get_tipo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    context.user_data["tipo"] = query.data
    keyboard = [
        [InlineKeyboardButton("💵 Pagó", callback_data="si")],
        [InlineKeyboardButton("❌ No pagó", callback_data="no")]
    ]
    await query.edit_message_text("¿El paciente pagó?", reply_markup=InlineKeyboardMarkup(keyboard))
    return PAGO

# Pago (botón) -> guardar
async def get_pago(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    pago_val = 1 if query.data == "si" else 0
    nombre = context.user_data.get("nombre", "Sin nombre")
    tipo = context.user_data.get("tipo", "desconocido")
    fecha = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    c.execute("INSERT INTO sesiones (nombre, tipo, pago, fecha) VALUES (?, ?, ?, ?)",
              (nombre, tipo, pago_val, fecha))
    conn.commit()

    await query.edit_message_text(f"✅ Sesión registrada:\n\n👤 {nombre}\n📂 {tipo}\n💰 {'Pagó' if pago_val else 'No pagó'}\n🗓️ {fecha}")
    return ConversationHandler.END

# Cancelar
async def cancelar(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("❌ Registro cancelado.")
    return ConversationHandler.END

# Buscar por nombre (comando opcional)
async def buscar(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("⚠️ Uso: /buscar NombrePaciente")
        return
    nombre = " ".join(context.args)
    c.execute("SELECT nombre, tipo, pago, fecha FROM sesiones WHERE nombre LIKE ? ORDER BY fecha DESC", (f"%{nombre}%",))
    rows = c.fetchall()
    texto = "\n".join([f"{r[0]} | {r[1]} | {'✅' if r[2] else '❌'} | {r[3]}" for r in rows]) or "No se encontraron registros."
    await update.message.reply_text(texto)

# Filtrar mes / reporte
async def mes(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("⚠️ Uso: /mes YYYY-MM")
        return
    periodo = context.args[0]
    c.execute("SELECT nombre, tipo, pago, fecha FROM sesiones WHERE strftime('%Y-%m', fecha) = ?", (periodo,))
    rows = c.fetchall()
    texto = "\n".join([f"{r[0]} | {r[1]} | {'✅' if r[2] else '❌'} | {r[3]}" for r in rows]) or "No hay registros en ese mes."
    await update.message.reply_text(texto)

async def reporte(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("⚠️ Uso: /reporte YYYY-MM")
        return
    periodo = context.args[0]
    c.execute("SELECT COUNT(*), SUM(pago) FROM sesiones WHERE strftime('%Y-%m', fecha) = ?", (periodo,))
    total, pagados = c.fetchone()
    pagados = pagados or 0
    await update.message.reply_text(f"📊 Reporte {periodo}\nTotal sesiones: {total}\nPagadas: {pagados}\nImpagas: {total - pagados}")

# --- Main ---
def main():
    app = Application.builder().token(TOKEN).build()

    conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(menu, pattern="^registrar$")],
        states={
            NOMBRE: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_nombre)],
            TIPO: [CallbackQueryHandler(get_tipo, pattern="^(particular|obra_social)$")],
            PAGO: [CallbackQueryHandler(get_pago, pattern="^(si|no)$")],
        },
        fallbacks=[CommandHandler("cancelar", cancelar)],
        per_user=True
    )

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(menu, pattern="^(listar|reporte_mes)$"))
    app.add_handler(conv)
    app.add_handler(CommandHandler("buscar", buscar))
    app.add_handler(CommandHandler("mes", mes))
    app.add_handler(CommandHandler("reporte", reporte))

    print("Bot corriendo... Ctrl+C para salir")
    app.run_polling()

if __name__ == "__main__":
    main()
