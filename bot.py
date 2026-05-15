import os
import json
import logging
from datetime import datetime, timedelta
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, MessageHandler,
    CallbackQueryHandler, ContextTypes, filters
)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

TOKEN = os.environ.get("BOT_TOKEN") or ""
TOKEN = TOKEN.strip().strip('"').strip("'")
logger.info(f"TOKEN inicio: '{TOKEN[:15]}' longitud={len(TOKEN)}")
if not TOKEN or ":" not in TOKEN:
    raise RuntimeError(f"BOT_TOKEN invalido. Valor recibido: '{TOKEN}'")

import re as _re
SUPERVISORS = []
_raw = os.environ.get("SUPERVISOR_IDS", "")
if _raw:
    try:
        SUPERVISORS = [int(i) for i in _re.findall(r'\d+', _raw)]
    except Exception:
        pass
DATA_FILE = "data.json"

# ─── Persistencia ────────────────────────────────────────────────────────────
def load_data():
    if os.path.exists(DATA_FILE):
        with open(DATA_FILE, "r") as f:
            return json.load(f)
    return {"cursos": {}, "boletines": [], "fotos": []}

def save_data(data):
    with open(DATA_FILE, "w") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

# ─── Helpers ─────────────────────────────────────────────────────────────────
def is_supervisor(user_id):
    return user_id in SUPERVISORS

def fmt(text):
    return text  # sin escape extra para MarkdownV2 por simplicidad

# ─── /start ──────────────────────────────────────────────────────────────────
async def start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if is_supervisor(uid):
        msg = (
            "👋 *Hola Supervisor*\n\n"
            "Comandos disponibles:\n"
            "📢 /boletin — Publicar boletin\n"
            "📚 /curso — Crear nuevo curso\n"
            "✅ /completados — Ver quién completó un curso\n"
            "📋 /pendientes — Ver quién NO ha completado\n"
            "📌 /fijar — Fijar último boletin/curso\n"
            "📸 /fotos — Ver fotos del equipo"
        )
    else:
        msg = (
            "👋 *Hola Embajador*\n\n"
            "Comandos disponibles:\n"
            "✅ /hice — Marcar curso como completado\n"
            "📸 Sube fotos directo al grupo con descripción\n"
            "📋 /miscursos — Ver tus cursos pendientes"
        )
    await update.message.reply_text(msg, parse_mode="Markdown")

# ─── /boletin ────────────────────────────────────────────────────────────────
async def boletin(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_supervisor(update.effective_user.id):
        await update.message.reply_text("❌ Solo supervisores pueden publicar boletines.")
        return
    if not ctx.args:
        await update.message.reply_text("Uso: /boletin <texto del boletin>")
        return
    texto = " ".join(ctx.args)
    data = load_data()
    entry = {
        "id": len(data["boletines"]) + 1,
        "texto": texto,
        "fecha": datetime.now().isoformat(),
        "autor": update.effective_user.full_name
    }
    data["boletines"].append(entry)
    save_data(data)
    msg = f"📢 *BOLETIN #{entry['id']}*\n\n{texto}\n\n_Publicado por {entry['autor']}_"
    sent = await update.message.reply_text(msg, parse_mode="Markdown")
    # Fijar automáticamente
    try:
        await ctx.bot.pin_chat_message(update.effective_chat.id, sent.message_id)
    except Exception:
        pass

# ─── /curso ──────────────────────────────────────────────────────────────────
async def curso(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_supervisor(update.effective_user.id):
        await update.message.reply_text("❌ Solo supervisores pueden crear cursos.")
        return
    # Formato: /curso NombreCurso | DD/MM/YYYY
    texto = " ".join(ctx.args)
    if "|" not in texto:
        await update.message.reply_text("Uso: /curso Nombre del curso | DD/MM/YYYY\nEjemplo: /curso Seguridad en pista | 20/05/2026")
        return
    partes = texto.split("|")
    nombre = partes[0].strip()
    fecha_limite = partes[1].strip()
    data = load_data()
    curso_id = f"curso_{len(data['cursos']) + 1}"
    data["cursos"][curso_id] = {
        "nombre": nombre,
        "fecha_limite": fecha_limite,
        "creado": datetime.now().isoformat(),
        "completados": []
    }
    save_data(data)
    msg = (
        f"📚 *NUEVO CURSO*\n\n"
        f"*{nombre}*\n"
        f"📅 Fecha límite: {fecha_limite}\n\n"
        f"Cuando lo completes escribe:\n`/hice {curso_id}`"
    )
    sent = await update.message.reply_text(msg, parse_mode="Markdown")
    try:
        await ctx.bot.pin_chat_message(update.effective_chat.id, sent.message_id)
    except Exception:
        pass
    # Programar recordatorio 1 día antes
    try:
        deadline = datetime.strptime(fecha_limite, "%d/%m/%Y")
        reminder_date = deadline - timedelta(days=1)
        delay = (reminder_date - datetime.now()).total_seconds()
        if delay > 0:
            ctx.job_queue.run_once(
                recordatorio_curso,
                when=delay,
                data={"chat_id": update.effective_chat.id, "curso_id": curso_id, "nombre": nombre, "fecha": fecha_limite}
            )
    except Exception as e:
        logger.warning(f"No se pudo programar recordatorio: {e}")

# ─── /hice ───────────────────────────────────────────────────────────────────
async def hice(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not ctx.args:
        data = load_data()
        if not data["cursos"]:
            await update.message.reply_text("No hay cursos registrados.")
            return
        keyboard = []
        for cid, c in data["cursos"].items():
            keyboard.append([InlineKeyboardButton(f"✅ {c['nombre']}", callback_data=f"hice_{cid}")])
        await update.message.reply_text("¿Qué curso completaste?", reply_markup=InlineKeyboardMarkup(keyboard))
        return
    curso_id = ctx.args[0]
    await _marcar_completado(update.effective_user, curso_id, update.message)

async def hice_callback(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    curso_id = query.data.replace("hice_", "")
    await _marcar_completado(query.from_user, curso_id, query.message)

async def _marcar_completado(user, curso_id, message):
    data = load_data()
    if curso_id not in data["cursos"]:
        await message.reply_text("❌ Curso no encontrado.")
        return
    curso_data = data["cursos"][curso_id]
    uid = str(user.id)
    if uid in [str(c["id"]) for c in curso_data["completados"]]:
        await message.reply_text(f"Ya marcaste *{curso_data['nombre']}* como completado ✅", parse_mode="Markdown")
        return
    curso_data["completados"].append({
        "id": user.id,
        "nombre": user.full_name,
        "fecha": datetime.now().isoformat()
    })
    save_data(data)
    await message.reply_text(f"✅ *{user.full_name}* completó el curso *{curso_data['nombre']}* 🎉", parse_mode="Markdown")

# ─── /completados ────────────────────────────────────────────────────────────
async def completados(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_supervisor(update.effective_user.id):
        await update.message.reply_text("❌ Solo supervisores.")
        return
    data = load_data()
    if not data["cursos"]:
        await update.message.reply_text("No hay cursos registrados.")
        return
    msg = "✅ *COMPLETADOS POR CURSO*\n\n"
    for cid, c in data["cursos"].items():
        msg += f"📚 *{c['nombre']}* (límite: {c['fecha_limite']})\n"
        if c["completados"]:
            for p in c["completados"]:
                msg += f"  • {p['nombre']}\n"
        else:
            msg += "  _Nadie aún_\n"
        msg += "\n"
    await update.message.reply_text(msg, parse_mode="Markdown")

# ─── /pendientes ─────────────────────────────────────────────────────────────
async def pendientes(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_supervisor(update.effective_user.id):
        await update.message.reply_text("❌ Solo supervisores.")
        return
    data = load_data()
    if not data["cursos"]:
        await update.message.reply_text("No hay cursos registrados.")
        return
    msg = "⏳ *PENDIENTES POR CURSO*\n\n"
    for cid, c in data["cursos"].items():
        completados_ids = [str(p["id"]) for p in c["completados"]]
        msg += f"📚 *{c['nombre']}* (límite: {c['fecha_limite']})\n"
        msg += f"  ✅ {len(completados_ids)} completados\n"
        msg += f"  ❌ Pendientes: ver lista con /completados\n\n"
    await update.message.reply_text(msg, parse_mode="Markdown")

# ─── /miscursos ──────────────────────────────────────────────────────────────
async def miscursos(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = str(update.effective_user.id)
    data = load_data()
    pendientes_lista = []
    completados_lista = []
    for cid, c in data["cursos"].items():
        ids = [str(p["id"]) for p in c["completados"]]
        if uid in ids:
            completados_lista.append(c["nombre"])
        else:
            pendientes_lista.append(f"{c['nombre']} (límite: {c['fecha_limite']})")
    msg = f"📋 *Tus cursos, {update.effective_user.first_name}*\n\n"
    if pendientes_lista:
        msg += "❌ *Pendientes:*\n" + "\n".join(f"  • {p}" for p in pendientes_lista) + "\n\n"
    if completados_lista:
        msg += "✅ *Completados:*\n" + "\n".join(f"  • {c}" for c in completados_lista)
    if not pendientes_lista and not completados_lista:
        msg += "_No hay cursos registrados aún._"
    await update.message.reply_text(msg, parse_mode="Markdown")

# ─── Fotos ───────────────────────────────────────────────────────────────────
async def foto_recibida(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not update.message.photo:
        return
    data = load_data()
    caption = update.message.caption or "(sin descripción)"
    data["fotos"].append({
        "usuario": update.effective_user.full_name,
        "usuario_id": update.effective_user.id,
        "caption": caption,
        "fecha": datetime.now().isoformat(),
        "file_id": update.message.photo[-1].file_id
    })
    save_data(data)
    await update.message.reply_text(f"📸 Foto guardada, gracias {update.effective_user.first_name}!")

# ─── Recordatorio automático ─────────────────────────────────────────────────
async def recordatorio_curso(ctx: ContextTypes.DEFAULT_TYPE):
    job = ctx.job
    d = job.data
    data = load_data()
    c = data["cursos"].get(d["curso_id"], {})
    completados_n = len(c.get("completados", []))
    msg = (
        f"⏰ *RECORDATORIO*\n\n"
        f"El curso *{d['nombre']}* vence mañana ({d['fecha']})\n"
        f"✅ {completados_n} personas lo han completado\n\n"
        f"Si aún no lo hiciste: `/hice {d['curso_id']}`"
    )
    await ctx.bot.send_message(d["chat_id"], msg, parse_mode="Markdown")

# ─── Main ─────────────────────────────────────────────────────────────────────
def main():
    app = Application.builder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("boletin", boletin))
    app.add_handler(CommandHandler("curso", curso))
    app.add_handler(CommandHandler("hice", hice))
    app.add_handler(CommandHandler("completados", completados))
    app.add_handler(CommandHandler("pendientes", pendientes))
    app.add_handler(CommandHandler("miscursos", miscursos))
    app.add_handler(CallbackQueryHandler(hice_callback, pattern="^hice_"))
    app.add_handler(MessageHandler(filters.PHOTO, foto_recibida))
    logger.info("Bot iniciado ✅")
    app.run_polling()

if __name__ == "__main__":
    main()
