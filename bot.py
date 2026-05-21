import os
import json
import logging
from datetime import datetime
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

TOKEN = os.environ.get("BOT_TOKEN", "").strip().strip('"').strip("'")
ADMIN_IDS = list(map(int, os.environ.get("ADMIN_IDS", "0").split(","))) if os.environ.get("ADMIN_IDS") else [0]
DATA_FILE = "embajadores_data.json"

if not TOKEN or ":" not in TOKEN:
    raise RuntimeError(f"BOT_TOKEN inválido: '{TOKEN}'")

logger.info(f"✅ TOKEN cargado: {TOKEN[:20]}...")

def load_data():
    if os.path.exists(DATA_FILE):
        with open(DATA_FILE, "r") as f:
            return json.load(f)
    return {"boletines": [], "cursos": {}, "boletin_counter": 0}

def save_data(data):
    with open(DATA_FILE, "w") as f:
        json.dump(data, f, indent=2)

def is_admin(user_id):
    return user_id in ADMIN_IDS

# ─── Comandos ───────────────────────────────────────────────────────────────
async def start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    msg = (
        "✈️ *Embajadores Volaris*\n\n"
        "*Comandos disponibles:*\n\n"
        "📋 `/boletin` — Publica un boletín\n"
        "📚 `/curso` — Crea un curso\n"
        "✅ `/completados` — Muestra completados\n"
        "⏳ `/pendientes` — Resumen de pendientes\n"
        "🗑️ `/borrar_boletin` — Elimina boletín\n"
        "🗑️ `/borrar_curso` — Elimina curso"
    )
    await update.message.reply_text(msg, parse_mode="Markdown")

async def boletin(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Publica un boletín en el grupo"""
    # Obtener el texto completo incluyendo saltos de línea
    texto_completo = update.message.text
    
    # Remover el comando /boletin
    if texto_completo.startswith("/boletin"):
        texto = texto_completo.replace("/boletin", "", 1).strip()
    else:
        texto = ""
    
    if not texto:
        await update.message.reply_text("❌ Escribe: `/boletin Tu texto aquí`", parse_mode="Markdown")
        return
    
    data = load_data()
    data["boletin_counter"] += 1
    numero = data["boletin_counter"]
    
    mensaje = f"📋 *BOLETÍN #{numero}*\n\n{texto}\n\n🌙 _Turno nocturno_"
    
    try:
        sent_msg = await ctx.bot.send_message(
            chat_id=update.effective_chat.id,
            text=mensaje,
            parse_mode="Markdown"
        )
        
        await ctx.bot.pin_chat_message(
            chat_id=update.effective_chat.id,
            message_id=sent_msg.message_id,
            disable_notification=True
        )
        
        data["boletines"].append({
            "numero": numero,
            "texto": texto,
            "message_id": sent_msg.message_id
        })
        save_data(data)
        logger.info(f"✅ Boletín #{numero} publicado")
    except Exception as e:
        logger.error(f"Error: {e}")
        await update.message.reply_text(f"❌ Error: {str(e)}")

async def curso(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Crea un curso con fecha"""
    if len(ctx.args) < 2:
        await update.message.reply_text("❌ Uso: `/curso nombre_curso YYYY-MM-DD`", parse_mode="Markdown")
        return
    
    nombre = " ".join(ctx.args[:-1])
    fecha = ctx.args[-1]
    
    data = load_data()
    curso_id = len(data["cursos"]) + 1
    
    data["cursos"][str(curso_id)] = {
        "nombre": nombre,
        "fecha": fecha,
        "completados": [],
        "message_id": None
    }
    
    mensaje = f"📚 *CURSO #{curso_id}*\n*{nombre}*\n⏰ Vence: {fecha}"
    
    try:
        sent_msg = await ctx.bot.send_message(
            chat_id=update.effective_chat.id,
            text=mensaje,
            parse_mode="Markdown"
        )
        
        data["cursos"][str(curso_id)]["message_id"] = sent_msg.message_id
        save_data(data)
        
        await ctx.bot.pin_chat_message(
            chat_id=update.effective_chat.id,
            message_id=sent_msg.message_id,
            disable_notification=True
        )
        logger.info(f"✅ Curso #{curso_id} creado")
    except Exception as e:
        logger.error(f"Error: {e}")

async def completados(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Muestra quién completó los cursos"""
    data = load_data()
    
    if not data["cursos"]:
        await update.message.reply_text("❌ No hay cursos")
        return
    
    mensaje = "✅ *COMPLETADOS*\n\n"
    for curso in data["cursos"].values():
        completados_list = ", ".join(curso["completados"]) if curso["completados"] else "Nadie aún"
        mensaje += f"📚 *{curso['nombre']}*\n{completados_list}\n\n"
    
    await update.message.reply_text(mensaje, parse_mode="Markdown")

async def pendientes(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Resumen de tareas pendientes"""
    data = load_data()
    
    mensaje = "⏳ *PENDIENTES*\n\n"
    if data["boletines"]:
        mensaje += f"📋 Último boletín: #{data['boletines'][-1]['numero']}\n\n"
    
    if data["cursos"]:
        mensaje += "📚 *Cursos activos:*\n"
        for curso in data["cursos"].values():
            mensaje += f"• {curso['nombre']} - Vence {curso['fecha']}\n"
    else:
        mensaje += "✅ Sin cursos pendientes"
    
    await update.message.reply_text(mensaje, parse_mode="Markdown")

async def borrar_boletin(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Elimina el último boletín (solo admins)"""
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("❌ No tienes permisos")
        return
    
    data = load_data()
    if not data["boletines"]:
        await update.message.reply_text("❌ No hay boletines para borrar")
        return
    
    ultimo = data["boletines"].pop()
    try:
        await ctx.bot.delete_message(
            chat_id=update.effective_chat.id,
            message_id=ultimo["message_id"]
        )
        save_data(data)
        await update.message.reply_text(f"✅ Boletín #{ultimo['numero']} eliminado")
    except Exception as e:
        logger.error(f"Error: {e}")

async def borrar_curso(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Elimina un curso (solo admins)"""
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("❌ No tienes permisos")
        return
    
    if not ctx.args:
        await update.message.reply_text("❌ Uso: `/borrar_curso ID`", parse_mode="Markdown")
        return
    
    data = load_data()
    curso_id = ctx.args[0]
    
    if curso_id not in data["cursos"]:
        await update.message.reply_text("❌ Curso no encontrado")
        return
    
    curso = data["cursos"].pop(curso_id)
    save_data(data)
    
    try:
        if curso["message_id"]:
            await ctx.bot.delete_message(
                chat_id=update.effective_chat.id,
                message_id=curso["message_id"]
            )
        await update.message.reply_text(f"✅ Curso '{curso['nombre']}' eliminado")
    except Exception as e:
        logger.error(f"Error: {e}")

# ─── Main ───────────────────────────────────────────────────────────────────
def main():
    app = Application.builder().token(TOKEN).build()
    
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("boletin", boletin))
    app.add_handler(CommandHandler("curso", curso))
    app.add_handler(CommandHandler("completados", completados))
    app.add_handler(CommandHandler("pendientes", pendientes))
    app.add_handler(CommandHandler("borrar_boletin", borrar_boletin))
    app.add_handler(CommandHandler("borrar_curso", borrar_curso))
    
    logger.info("🚀 Bot Embajadores Volaris iniciado")
    app.run_polling()

if __name__ == "__main__":
    main()
