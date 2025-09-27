import os
import sqlite3
from datetime import datetime
from telegram import (
    Update, ReplyKeyboardMarkup,
    InlineKeyboardMarkup, InlineKeyboardButton
)
from telegram.ext import (
    Application, CommandHandler, MessageHandler, filters,
    ContextTypes, CallbackQueryHandler, ConversationHandler
)

# ------------------ CONFIGURACIÓN DE BASE DE DATOS ------------------
conn = sqlite3.connect("pacientes.db", check_same_thread=False)
c = conn.cursor()
c.execute("""
CREATE TABLE IF NOT EXISTS sesiones (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    nombre TEXT,
    tipo TEXT,
    pago INTEGER,
    monto REAL DEFAULT 0,
    fecha TEXT
)
""")
conn.commit()

# Intentar agregar columna "monto" si no existe
try:
    c.execute("ALTER TABLE sesiones ADD COLUMN monto REAL DEFAULT 0")
    conn.commit()
except sqlite3.OperationalError:
    pass  # ya existe

# ------------------ MENÚ PRINCIPAL ------------------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        ["➕ Nueva sesión"],
        ["📋 Ver impagos"],
        ["📊 Reporte mensual"]
    ]
    reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
    await update.message.reply_text("Bienvenido al registro de pacientes 🧑‍⚕️", reply_markup=reply_markup)

# ------------------ REGISTRO DE SESIONES ------------------
async def nueva_sesion(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Escribí: Nombre, Tipo, Pago(Si/No) o Monto (ej: Juan Perez, Particular, 2000)")

async def guardar_sesion(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        partes = [x.strip() for x in update.message.text.split(",")]
        if len(partes) != 3:
            raise ValueError("Formato incorrecto")
        nombre, tipo, valor = partes

        if valor.replace(".", "").isdigit():
            monto = float(valor)
            pago = 1 if monto > 0 else 0
        else:
            pago = 1 if valor.lower() in ["si", "sí"] else 0
            monto = 0

        fecha = datetime.now().strftime("%Y-%m-%d")
        c.execute("INSERT INTO sesiones (nombre, tipo, pago, monto, fecha) VALUES (?, ?, ?, ?, ?)",
                  (nombre, tipo, pago, monto, fecha))
        conn.commit()

        await update.message.reply_text(
            f"✅ Sesión guardada:\n{nombre} | {tipo} | {'Pagó' if pago else 'Impago'} | Monto: ${monto} | {fecha}"
        )
    except Exception as e:
        await update.message.reply_text("❌ Error. Usá el formato: Nombre, Tipo, Pago(Si/No) o Monto")
        print(e)

# ------------------ LISTAR IMPAGOS ------------------
async def listar_impagos(update: Update, context: ContextTypes.DEFAULT_TYPE):
    c.execute("SELECT id, nombre, tipo, fecha FROM sesiones WHERE pago = 0 ORDER BY fecha DESC")
    rows = c.fetchall()
    if not rows:
        await update.message.reply_text("No hay sesiones impagas. ✅")
        return

    for r in rows:
        id_, nombre, tipo, fecha = r
        texto = f"ID:{id_} | {nombre} | {tipo} | {fecha} | ❌ Impago"
        keyboard = [[InlineKeyboardButton("💵 Marcar pagado", callback_data=f"marcar_{id_}")]]
        await update.message.reply_text(texto, reply_markup=InlineKeyboardMarkup(keyboard))

# ------------------ CALLBACKS PARA PAGOS ------------------
# Estados para ConversationHandler
ESPERANDO_MONTO = 1

async def marcar_pago_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data

    if data.startswith("marcar_"):
        id_int = int(data.split("_")[1])
        context.user_data["id_a_marcar"] = id_int
        await query.message.reply_text("💰 ¿Cuánto pagó el paciente?")
        return ESPERANDO_MONTO

    elif data.startswith("desmarcar_"):
        id_int = int(data.split("_")[1])
        c.execute("UPDATE sesiones SET pago = 0, monto = 0 WHERE id = ?", (id_int,))
        conn.commit()
        c.execute("SELECT nombre, tipo, fecha FROM sesiones WHERE id = ?", (id_int,))
        row = c.fetchone()
        if row:
            nombre, tipo, fecha = row
            keyboard = [[InlineKeyboardButton("💵 Marcar pagado", callback_data=f"marcar_{id_int}")]]
            await query.edit_message_text(f"❌ Impago:\nID:{id_int} | {nombre} | {tipo} | {fecha}",
                                          reply_markup=InlineKeyboardMarkup(keyboard))
        return ConversationHandler.END

async def guardar_monto(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        monto = float(update.message.text.strip())
        id_int = context.user_data.get("id_a_marcar")

        c.execute("UPDATE sesiones SET pago = 1, monto = ? WHERE id = ?", (monto, id_int))
        conn.commit()

        c.execute("SELECT nombre, tipo, fecha FROM sesiones WHERE id = ?", (id_int,))
        row = c.fetchone()
        if row:
            nombre, tipo, fecha = row
            keyboard = [[InlineKeyboardButton("↩️ Desmarcar", callback_data=f"desmarcar_{id_int}")]]
            await update.message.reply_text(
                f"✅ Pagado:\nID:{id_int} | {nombre} | {tipo} | ${monto} | {fecha}",
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
    except Exception:
        await update.message.reply_text("❌ Error: escribí un número válido.")
    return ConversationHandler.END

# ------------------ REPORTE MENSUAL ------------------
async def reporte_mensual(update: Update, context: ContextTypes.DEFAULT_TYPE):
    mes = datetime.now().strftime("%Y-%m")
    c.execute("SELECT COUNT(*) FROM sesiones WHERE fecha LIKE ?", (f"{mes}%",))
    total = c.fetchone()[0]
    c.execute("SELECT COUNT(*) FROM sesiones WHERE fecha LIKE ? AND pago = 1", (f"{mes}%",))
    pagados = c.fetchone()[0]
    c.execute("SELECT SUM(monto) FROM sesiones WHERE fecha LIKE ?", (f"{mes}%",))
    total_facturado = c.fetchone()[0] or 0
    await update.message.reply_text(
        f"📊 Reporte {mes}:\n"
        f"Total sesiones: {total}\n"
        f"Pagadas: {pagados}\n"
        f"Impagas: {total - pagados}\n"
        f"Facturación: ${total_facturado:,.0f}"
    )

# ------------------ MAIN ------------------
def main():
    BOT_TOKEN = os.getenv("BOT_TOKEN")
    app = Application.builder().token(BOT_TOKEN).build()

    # Comandos
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("impagos", listar_impagos))
    app.add_handler(CommandHandler("reporte", reporte_mensual))

    # Botones / textos del menú
    app.add_handler(MessageHandler(filters.Regex("^➕ Nueva sesión$"), nueva_sesion))
    app.add_handler(MessageHandler(filters.Regex("^📋 Ver impagos$"), listar_impagos))
    app.add_handler(MessageHandler(filters.Regex("^📊 Reporte mensual$"), reporte_mensual))

    # Guardar sesión si el mensaje es en formato correcto
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, guardar_sesion))

    # ConversationHandler para manejar "Marcar pagado" → ingresar monto
    conv_handler = ConversationHandler(
        entry_points=[CallbackQueryHandler(marcar_pago_callback, pattern="^(marcar_|desmarcar_)")],
        states={ESPERANDO_MONTO: [MessageHandler(filters.TEXT & ~filters.COMMAND, guardar_monto)]},
        fallbacks=[]
    )
    app.add_handler(conv_handler)

    print("🤖 Bot en marcha con monto...")
    app.run_polling()

if __name__ == "__main__":
    main()
