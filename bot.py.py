import os
import json
import logging
from datetime import datetime
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

TOKEN = os.environ.get("BOT_TOKEN", "").strip().strip('"').strip("'")
ADMIN_IDS = list(map(int, os.environ.get("ADMIN_IDS", "0").split(","))) if os.environ.get("ADMIN_IDS") else [0]
DATA_FILE = "embajadores_data.json"

if not TOKEN or ":" not in TOKEN:
    raise RuntimeError(f"BOT_TOKEN inválido: '{TOKEN}'")

logger.info(f"✅ TOKEN cargado: {TOKEN[:20]}...")
logger.info(f"✅ ADMIN_IDS: {ADMIN_IDS}")

# ─── Funciones de datos ──────────────────────────────────────────────────────
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

# ─── Comandos ─────────────────────────────────────────────────────────────
async def start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Comando /start"""
    msg = (
        "✈️ *Embajadores Volaris*\n\n"
        "*Comandos disponibles:*\n\n"
        "📋 `/boletin_simple` — Boletín fácil (ej: `/boletin_simple Mane|Revisar aceite|Adriana|Revisar cubetas`)\n"
        "📋 `/boletin` — Boletín custom (con saltos de línea)\n"
        "📚 `/curso` — Crea un curso con fecha (ej: `/curso Seguridad 2024-05-30`)\n"
        "✅ `/completados` — Muestra quién completó cursos\n"
        "⏳ `/pendientes` — Resumen de pendientes\n"
        "🗑️ `/borrar_boletin` — Elimina el último boletín\n"
        "🗑️ `/borrar_curso` — Elimina un curso\n\n"
        "_Solo admins pueden ejecutar comandos de eliminación_"
    )
    await update.message.reply_text(msg, parse_mode="Markdown")

async def boletin(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Comando /boletin - publica boletín formateado"""
    # Obtener el texto completo preservando saltos de línea
    texto_completo = update.message.text
    
    # Remover el comando /boletin
    if texto_completo.startswith("/boletin"):
        texto = texto_completo.replace("/boletin", "", 1).strip()
    else:
        texto = texto_completo
    
    if not texto:
        await update.message.reply_text("❌ Usa: `/boletin Tu contenido aquí`", parse_mode="Markdown")
        return
    
    data = load_data()
    data["boletin_counter"] += 1
    numero = data["boletin_counter"]
    
    # Mensaje formateado con HTML
    mensaje = f"📋 <b>BOLETÍN #{numero}</b>\n\n{texto}\n\n🌙 <i>Turno nocturno</i>"
    
    try:
        # Enviar al grupo
        sent_msg = await ctx.bot.send_message(
            chat_id=update.effective_chat.id,
            text=mensaje,
            parse_mode="HTML"
        )
        
        # Fijar el mensaje
        await ctx.bot.pin_chat_message(
            chat_id=update.effective_chat.id,
            message_id=sent_msg.message_id,
            disable_notification=True
        )
        
        # Guardar en datos
        data["boletines"].append({
            "numero": numero,
            "texto": texto,
            "fecha": datetime.now().isoformat(),
            "message_id": sent_msg.message_id
        })
        save_data(data)
        
        logger.info(f"✅ Boletín #{numero} publicado")
    except Exception as e:
        await update.message.reply_text(f"❌ Error: {str(e)}", parse_mode="Markdown")

async def boletin_simple(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Comando /boletin_simple - formato simple para celular (Persona|Tarea|Persona|Tarea)"""
    if not ctx.args:
        await update.message.reply_text(
            "❌ Uso: `/boletin_simple Persona1|Tarea1|Persona2|Tarea2|...`\n\n"
            "Ejemplo: `/boletin_simple Mane y Joshua|Revisar aceite|Adriana y Brayan|Revisar cubetas|Laura y Aldo|Sacar material`",
            parse_mode="Markdown"
        )
        return
    
    texto_completo = " ".join(ctx.args)
    items = texto_completo.split("|")
    
    if len(items) < 2 or len(items) % 2 != 0:
        await update.message.reply_text(
            "❌ Debe haber parejas Persona|Tarea\n"
            "Ejemplo: `/boletin_simple Mane|Revisar aceite|Adriana|Revisar cubetas`",
            parse_mode="Markdown"
        )
        return
    
    data = load_data()
    data["boletin_counter"] += 1
    numero = data["boletin_counter"]
    
    # Construir boletín formateado
    emojis = ["⚠️", "🚨", "📦", "🔧", "📋", "✈️", "🛠️", "⚡"]
    lineas = []
    
    for i in range(0, len(items), 2):
        emoji = emojis[(i // 2) % len(emojis)]
        persona = items[i].strip()
        tarea = items[i + 1].strip()
        lineas.append(f"{emoji} <b>{persona}</b>\n• {tarea}")
    
    contenido = "\n\n".join(lineas)
    mensaje = f"📋 <b>BOLETÍN #{numero}</b>\n\n{contenido}\n\n🌙 <i>Turno nocturno</i>"
    
    try:
        sent_msg = await ctx.bot.send_message(
            chat_id=update.effective_chat.id,
            text=mensaje,
            parse_mode="HTML"
        )
        
        await ctx.bot.pin_chat_message(
            chat_id=update.effective_chat.id,
            message_id=sent_msg.message_id,
            disable_notification=True
        )
        
        data["boletines"].append({
            "numero": numero,
            "texto": contenido,
            "fecha": datetime.now().isoformat(),
            "message_id": sent_msg.message_id
        })
        save_data(data)
        logger.info(f"✅ Boletín simple #{numero} publicado")
    except Exception as e:
        await update.message.reply_text(f"❌ Error: {str(e)}", parse_mode="Markdown")

async def borrar_boletin(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Comando /borrar_boletin - solo para admins"""
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("❌ No tienes permisos", parse_mode="Markdown")
        return
    
    data = load_data()
    if not data["boletines"]:
        await update.message.reply_text("❌ No hay boletines para borrar", parse_mode="Markdown")
        return
    
    ultimo = data["boletines"].pop()
    try:
        await ctx.bot.delete_message(
            chat_id=update.effective_chat.id,
            message_id=ultimo["message_id"]
        )
        save_data(data)
        await update.message.reply_text(f"✅ Boletín #{ultimo['numero']} eliminado", parse_mode="Markdown")
    except Exception as e:
        await update.message.reply_text(f"❌ Error al eliminar: {str(e)}", parse_mode="Markdown")

async def curso(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Comando /curso - crea un curso con fecha límite"""
    if len(ctx.args) < 2:
        await update.message.reply_text(
            "❌ Uso: `/curso nombre_curso YYYY-MM-DD`\nEj: `/curso Seguridad 2024-05-30`",
            parse_mode="Markdown"
        )
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
    save_data(data)
    
    mensaje = f"📚 *CURSO #{curso_id}*\n\n*{nombre}*\n⏰ Vence: {fecha}\n✅ Completados: 0"
    
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
        await update.message.reply_text(f"❌ Error: {str(e)}", parse_mode="Markdown")

async def completados(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Comando /completados - muestra quién completó"""
    data = load_data()
    
    if not data["cursos"]:
        await update.message.reply_text("❌ No hay cursos", parse_mode="Markdown")
        return
    
    mensaje = "✅ *COMPLETADOS*\n\n"
    for curso_id, curso in data["cursos"].items():
        completados_list = ", ".join(curso["completados"]) if curso["completados"] else "Nadie aún"
        mensaje += f"📚 *{curso['nombre']}*\n{completados_list}\n\n"
    
    await update.message.reply_text(mensaje, parse_mode="Markdown")

async def pendientes(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Comando /pendientes - resumen de tareas pendientes"""
    data = load_data()
    
    mensaje = "⏳ *PENDIENTES*\n\n"
    if data["boletines"]:
        mensaje += f"📋 Último boletín: #{data['boletines'][-1]['numero']}\n\n"
    
    if data["cursos"]:
        mensaje += "📚 *Cursos activos:*\n"
        for curso in data["cursos"].values():
            pendientes_count = 3  # Ajusta según tu lógica
            mensaje += f"• {curso['nombre']} - Vence {curso['fecha']}\n"
    else:
        mensaje += "✅ Sin cursos pendientes"
    
    await update.message.reply_text(mensaje, parse_mode="Markdown")

async def borrar_curso(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Comando /borrar_curso - solo para admins"""
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("❌ No tienes permisos", parse_mode="Markdown")
        return
    
    if not ctx.args:
        await update.message.reply_text("❌ Uso: `/borrar_curso ID`", parse_mode="Markdown")
        return
    
    data = load_data()
    curso_id = ctx.args[0]
    
    if curso_id not in data["cursos"]:
        await update.message.reply_text("❌ Curso no encontrado", parse_mode="Markdown")
        return
    
    curso = data["cursos"].pop(curso_id)
    save_data(data)
    
    try:
        if curso["message_id"]:
            await ctx.bot.delete_message(
                chat_id=update.effective_chat.id,
                message_id=curso["message_id"]
            )
        await update.message.reply_text(f"✅ Curso '{curso['nombre']}' eliminado", parse_mode="Markdown")
    except Exception as e:
        await update.message.reply_text(f"❌ Error: {str(e)}", parse_mode="Markdown")

# ─── Main ───────────────────────────────────────────────────────────────────
def main():
    app = Application.builder().token(TOKEN).build()
    
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("boletin", boletin))
    app.add_handler(CommandHandler("boletin_simple", boletin_simple))
    app.add_handler(CommandHandler("curso", curso))
    app.add_handler(CommandHandler("completados", completados))
    app.add_handler(CommandHandler("pendientes", pendientes))
    app.add_handler(CommandHandler("borrar_boletin", borrar_boletin))
    app.add_handler(CommandHandler("borrar_curso", borrar_curso))
    
    logger.info("🚀 Bot Embajadores Volaris iniciado")
    logger.info("✅ Comandos cargados: /start /boletin /curso /completados /pendientes /borrar_boletin /borrar_curso")
    
    app.run_polling()

if __name__ == "__main__":
    main()
