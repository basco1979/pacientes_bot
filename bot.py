import os
import psycopg2
from datetime import datetime, timedelta
from telegram import Update, ReplyKeyboardMarkup, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, MessageHandler, filters,
    CallbackQueryHandler, ConversationHandler, ContextTypes
)

# -------------------------------
# CONFIGURACIÓN DE SUPABASE
# -------------------------------
DB_CONFIG = {
    "dbname": "postgres",                 # suele ser "postgres"
    "user": "postgres",                   # usuario
    "password": "Gs5Qfy57fU2GAqCt",   # contraseña que definiste
    "host": "db.kjguldjmpiehomkehvcv.supabase.co",           # ej: db.abcd1234.supabase.co
    "port": "5432"
}

conn = psycopg2.connect("postgres://postgres.kjguldjmpiehomkehvcv:Gs5Qfy57fU2GAqCt@aws-1-sa-east-1.pooler.supabase.com:5432/postgres?sslmode=require")
c = conn.cursor()

# Crear tablas si no existen
c.execute("""
CREATE TABLE IF NOT EXISTS pacientes (
    id SERIAL PRIMARY KEY,
    nombre TEXT NOT NULL,
    tipo TEXT NOT NULL
)
""")
c.execute("""
CREATE TABLE IF NOT EXISTS sesiones (
    id SERIAL PRIMARY KEY,
    paciente_id INT REFERENCES pacientes(id),
    fecha DATE NOT NULL,
    pago BOOLEAN NOT NULL,
    monto REAL DEFAULT 0
)
""")
conn.commit()

# -------------------------------
# BOT
# -------------------------------
ESPERANDO_MONTO = 1
sesion_en_edicion = {}

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        ["➕ Nueva sesión"],
        ["📋 Ver impagos"],
        ["📊 Reporte mensual"],
        ["📆 Reporte semanal"]
    ]
    reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
    await update.message.reply_text("Bienvenido. ¿Qué deseas hacer?", reply_markup=reply_markup)

# Guardar nueva sesión
async def guardar_sesion(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        datos = update.message.text.split(",")
        if len(datos) < 2:
            await update.message.reply_text("Formato: Nombre, Tipo, [Monto o Pago Si/No]")
            return

        nombre, tipo = datos[0].strip(), datos[1].strip()
        monto, pago = 0, False

        if len(datos) == 3:
            tercero = datos[2].strip()
            if tercero.isdigit():
                monto = float(tercero)
                pago = True
            else:
                pago = (tercero.lower() == "si")

        # Insertar paciente si no existe
        c.execute("SELECT id FROM pacientes WHERE nombre=%s", (nombre,))
        paciente = c.fetchone()
        if paciente:
            paciente_id = paciente[0]
        else:
            c.execute("INSERT INTO pacientes (nombre, tipo) VALUES (%s,%s) RETURNING id", (nombre, tipo))
            paciente_id = c.fetchone()[0]

        # Insertar sesión
        fecha = datetime.now().date()
        c.execute("INSERT INTO sesiones (paciente_id, fecha, pago, monto) VALUES (%s,%s,%s,%s)",
                  (paciente_id, fecha, pago, monto))
        conn.commit()

        await update.message.reply_text(f"✅ Sesión registrada: {nombre}, {tipo}, pago={pago}, monto={monto}")
    except Exception as e:
        await update.message.reply_text(f"⚠️ Error: {e}")

# Ver impagos
async def ver_impagos(update: Update, context: ContextTypes.DEFAULT_TYPE):
    c.execute("""SELECT s.id, p.nombre, s.fecha FROM sesiones s
                 JOIN pacientes p ON s.paciente_id=p.id
                 WHERE s.pago = FALSE ORDER BY s.fecha DESC""")
    filas = c.fetchall()
    if not filas:
        await update.message.reply_text("No hay sesiones impagas ✅")
        return

    for fila in filas:
        sesion_id, nombre, fecha = fila
        botones = [[InlineKeyboardButton("💵 Marcar pagado", callback_data=f"marcar_{sesion_id}")]]
        await update.message.reply_text(f"{nombre} - {fecha}", reply_markup=InlineKeyboardMarkup(botones))

# Callback para marcar pago
async def marcar_pago_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    sesion_id = int(query.data.split("_")[1])
    sesion_en_edicion[query.from_user.id] = sesion_id
    await query.edit_message_text("💵 Ingrese el monto pagado:")
    return ESPERANDO_MONTO

async def guardar_monto(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        monto = float(update.message.text)
        sesion_id = sesion_en_edicion.pop(update.message.from_user.id)

        c.execute("UPDATE sesiones SET pago=TRUE, monto=%s WHERE id=%s", (monto, sesion_id))
        conn.commit()

        await update.message.reply_text(f"✅ Sesión actualizada. Monto: ${monto}")
    except Exception as e:
        await update.message.reply_text(f"⚠️ Error: {e}")
    return ConversationHandler.END

# Reporte mensual
async def reporte_mensual(update: Update, context: ContextTypes.DEFAULT_TYPE):
    mes = datetime.now().strftime("%Y-%m")
    c.execute("SELECT COUNT(*) FROM sesiones WHERE TO_CHAR(fecha,'YYYY-MM')=%s", (mes,))
    total = c.fetchone()[0]
    c.execute("SELECT COUNT(*) FROM sesiones WHERE TO_CHAR(fecha,'YYYY-MM')=%s AND pago=TRUE", (mes,))
    pagados = c.fetchone()[0]
    c.execute("SELECT SUM(monto) FROM sesiones WHERE TO_CHAR(fecha,'YYYY-MM')=%s", (mes,))
    total_facturado = c.fetchone()[0] or 0

    await update.message.reply_text(
        f"📊 Reporte {mes}:\n"
        f"Total sesiones: {total}\n"
        f"Pagadas: {pagados}\n"
        f"Impagas: {total - pagados}\n"
        f"Facturación: ${total_facturado:,.0f}"
    )

# Reporte semanal
async def reporte_semanal(update: Update, context: ContextTypes.DEFAULT_TYPE):
    hoy = datetime.now().date()
    lunes = hoy - timedelta(days=hoy.weekday())
    domingo = lunes + timedelta(days=6)

    c.execute("SELECT COUNT(*) FROM sesiones WHERE fecha BETWEEN %s AND %s", (lunes, domingo))
    total = c.fetchone()[0]
    c.execute("SELECT COUNT(*) FROM sesiones WHERE fecha BETWEEN %s AND %s AND pago=TRUE", (lunes, domingo))
    pagados = c.fetchone()[0]
    c.execute("SELECT SUM(monto) FROM sesiones WHERE fecha BETWEEN %s AND %s", (lunes, domingo))
    total_facturado = c.fetchone()[0] or 0
    comision = total_facturado * 0.20

    await update.message.reply_text(
        f"📆 Reporte semanal ({lunes} → {domingo}):\n"
        f"Total sesiones: {total}\n"
        f"Pagadas: {pagados}\n"
        f"Impagas: {total - pagados}\n"
        f"Facturación: ${total_facturado:,.0f}\n"
        f"20% comisión: ${comision:,.0f}"
    )

def main():
    BOT_TOKEN = os.getenv("BOT_TOKEN") 
    app = Application.builder().token(BOT_TOKEN).build()

    conv_handler = ConversationHandler(
        entry_points=[CallbackQueryHandler(marcar_pago_callback, pattern="^marcar_")],
        states={ESPERANDO_MONTO: [MessageHandler(filters.TEXT & ~filters.COMMAND, guardar_monto)]},
        fallbacks=[]
    )
    app.add_handler(conv_handler)

    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.Regex("^➕ Nueva sesión$"), lambda u,c: u.message.reply_text("Enviá: Nombre, Tipo, [Monto o Pago]")))
    app.add_handler(MessageHandler(filters.Regex("^📋 Ver impagos$"), ver_impagos))
    app.add_handler(MessageHandler(filters.Regex("^📊 Reporte mensual$"), reporte_mensual))
    app.add_handler(MessageHandler(filters.Regex("^📆 Reporte semanal$"), reporte_semanal))
    app.add_handler(CommandHandler("reporte_mensual", reporte_mensual))
    app.add_handler(CommandHandler("reporte_semana", reporte_semanal))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, guardar_sesion))

    print("🤖 Bot conectado a Supabase...")
    app.run_polling()

if __name__ == "__main__":
    main()

