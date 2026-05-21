"""
Bot de Telegram — Embajadores Volaris
=====================================
Gestiona boletines, cursos y el guardado de imágenes para el grupo del turno.

Configuración por variables de entorno (ver .env.example):
    BOT_TOKEN     Token del bot (de @BotFather)
    ADMIN_IDS     IDs separados por coma; quienes pueden borrar
    DOWNLOAD_DIR  Carpeta base donde se guardan las imágenes
"""

import os
import json
import html
import shutil
import zipfile
import logging
import tempfile
from datetime import datetime

from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    ReactionTypeEmoji,
)
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ContextTypes,
    filters,
)

# Carga el .env automáticamente si python-dotenv está instalado (opcional).
try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:
    pass

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

# ─── Configuración ────────────────────────────────────────────────────────────
TOKEN = os.environ.get("BOT_TOKEN", "").strip().strip('"').strip("'")
DATA_FILE = os.environ.get("DATA_FILE", "embajadores_data.json")
PARSE = "HTML"  # HTML es más tolerante que Markdown con texto de usuarios

# Reacción del bot. El corazón es una reacción estándar de Telegram (no falla).
REACTION_EMOJIS = ("❤️", "❤", "👍")

# Límite de subida para bots en Telegram (50 MB). Lo dejamos en 49 por margen.
MAX_UPLOAD_MB = 49

# Carpeta base (EN LA PC/SERVIDOR donde corre el bot) para guardar imágenes.
BASE_DOWNLOAD_DIR = os.environ.get(
    "DOWNLOAD_DIR", os.path.join(os.getcwd(), "descargas")
)
# Clave interna -> nombre de subcarpeta. Edítalas a tu gusto.
DOWNLOAD_FOLDERS = {
    "boletines": "Boletines",
    "cursos": "Cursos",
    "evidencias": "Evidencias",
    "general": "General",
}

DEFAULT_DATA = {
    "boletines": [],
    "cursos": {},
    "imagenes": [],
    "boletin_counter": 0,
    "curso_counter": 0,
}


def _parse_admin_ids(raw: str) -> list[int]:
    ids = []
    for part in raw.split(","):
        part = part.strip()
        if part.lstrip("-").isdigit():
            ids.append(int(part))
    return ids


ADMIN_IDS = _parse_admin_ids(os.environ.get("ADMIN_IDS", ""))

if not TOKEN or ":" not in TOKEN:
    raise RuntimeError(
        "BOT_TOKEN inválido o ausente. Configúralo como variable de entorno."
    )

if not ADMIN_IDS:
    logger.warning("⚠️ No hay ADMIN_IDS configurados: nadie podrá borrar.")


# ─── Utilidades ────────────────────────────────────────────────────────────────
def esc(text: str | None) -> str:
    """Escapa texto de usuario para parse_mode=HTML."""
    return html.escape(text or "")


def load_data() -> dict:
    """Carga datos de forma robusta (archivo inexistente, corrupto o incompleto)."""
    if not os.path.exists(DATA_FILE):
        return {k: (v.copy() if isinstance(v, (list, dict)) else v) for k, v in DEFAULT_DATA.items()}
    try:
        with open(DATA_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (json.JSONDecodeError, OSError) as e:
        logger.error(f"No se pudo leer {DATA_FILE} ({e}); se usan datos vacíos.")
        data = {}
    for key, default in DEFAULT_DATA.items():
        data.setdefault(key, default.copy() if isinstance(default, (list, dict)) else default)
    return data


def save_data(data: dict) -> None:
    """Guardado seguro: escribe a un temporal y reemplaza (evita corrupción)."""
    tmp = f"{DATA_FILE}.tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    os.replace(tmp, DATA_FILE)


def is_admin(user_id: int) -> bool:
    return user_id in ADMIN_IDS


def _arg_text(update: Update) -> str:
    """Texto que sigue al comando, conservando saltos de línea y soportando
    /comando@nombredelbot en grupos."""
    text = update.message.text or ""
    partes = text.split(maxsplit=1)
    return partes[1].strip() if len(partes) > 1 else ""


def _folder_keyboard(prefix: str, extra_rows=None) -> InlineKeyboardMarkup:
    """Construye un teclado con las carpetas disponibles.
    prefix es la acción del callback (p. ej. 'dl_save' o 'all_save')."""
    items = list(DOWNLOAD_FOLDERS.items())
    filas = []
    for i in range(0, len(items), 2):
        fila = [
            InlineKeyboardButton(f"📁 {label}", callback_data=(prefix, key))
            for key, label in items[i : i + 2]
        ]
        filas.append(fila)
    if extra_rows:
        filas.extend(extra_rows)
    return InlineKeyboardMarkup(filas)


# ─── Comandos ────────────────────────────────────────────────────────────────
async def start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    msg = (
        "✈️ <b>Embajadores Volaris</b>\n\n"
        "<b>Comandos disponibles:</b>\n\n"
        "📋 <code>/boletin</code> — Publica un boletín\n"
        "📚 <code>/curso</code> — Crea un curso\n"
        "✅ <code>/completar ID</code> — Te marcas como que completaste un curso\n"
        "✅ <code>/completados</code> — Muestra completados\n"
        "⏳ <code>/pendientes</code> — Resumen de pendientes\n"
        "🖼️ <code>/descargar_todo</code> — Descarga TODAS las imágenes juntas\n"
        "🗑️ <code>/borrar_boletin</code> — Elimina el último boletín\n"
        "🗑️ <code>/borrar_curso ID</code> — Elimina un curso\n\n"
        "📷 Manda una <b>imagen</b>: el bot reacciona ❤️ y te da botón para guardarla."
    )
    await update.message.reply_text(msg, parse_mode=PARSE)


async def boletin(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Publica un boletín en el grupo y lo fija."""
    texto = _arg_text(update)
    if not texto:
        await update.message.reply_text(
            "❌ Escribe: <code>/boletin Tu texto aquí</code>", parse_mode=PARSE
        )
        return

    data = load_data()
    data["boletin_counter"] += 1
    numero = data["boletin_counter"]

    mensaje = f"📋 <b>BOLETÍN #{numero}</b>\n\n{esc(texto)}\n\n🌙 <i>Turno nocturno</i>"
    try:
        sent = await ctx.bot.send_message(
            chat_id=update.effective_chat.id, text=mensaje, parse_mode=PARSE
        )
        try:
            await ctx.bot.pin_chat_message(
                chat_id=update.effective_chat.id,
                message_id=sent.message_id,
                disable_notification=True,
            )
        except Exception as e:
            logger.warning(f"No se pudo fijar el boletín (¿el bot es admin?): {e}")

        data["boletines"].append(
            {"numero": numero, "texto": texto, "message_id": sent.message_id}
        )
        save_data(data)
        logger.info(f"✅ Boletín #{numero} publicado")
    except Exception as e:
        logger.error(f"Error en boletin: {e}")
        await update.message.reply_text(f"❌ Error: {esc(str(e))}", parse_mode=PARSE)


async def curso(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Crea un curso con fecha de vencimiento."""
    if len(ctx.args) < 2:
        await update.message.reply_text(
            "❌ Uso: <code>/curso nombre del curso YYYY-MM-DD</code>", parse_mode=PARSE
        )
        return

    nombre = " ".join(ctx.args[:-1])
    fecha = ctx.args[-1]

    try:
        datetime.strptime(fecha, "%Y-%m-%d")
    except ValueError:
        await update.message.reply_text(
            "❌ Fecha inválida. Usa el formato <code>YYYY-MM-DD</code> (ej. 2025-12-31).",
            parse_mode=PARSE,
        )
        return

    data = load_data()
    # Contador propio para evitar IDs duplicados al borrar cursos.
    data["curso_counter"] += 1
    curso_id = data["curso_counter"]

    data["cursos"][str(curso_id)] = {
        "nombre": nombre,
        "fecha": fecha,
        "completados": [],
        "message_id": None,
    }

    mensaje = f"📚 <b>CURSO #{curso_id}</b>\n<b>{esc(nombre)}</b>\n⏰ Vence: {esc(fecha)}"
    teclado = InlineKeyboardMarkup(
        [[InlineKeyboardButton("✅ Ya lo completé", callback_data=("done", curso_id))]]
    )
    try:
        sent = await ctx.bot.send_message(
            chat_id=update.effective_chat.id,
            text=mensaje,
            parse_mode=PARSE,
            reply_markup=teclado,
        )
        data["cursos"][str(curso_id)]["message_id"] = sent.message_id
        save_data(data)
        try:
            await ctx.bot.pin_chat_message(
                chat_id=update.effective_chat.id,
                message_id=sent.message_id,
                disable_notification=True,
            )
        except Exception as e:
            logger.warning(f"No se pudo fijar el curso: {e}")
        logger.info(f"✅ Curso #{curso_id} creado")
    except Exception as e:
        logger.error(f"Error en curso: {e}")
        await update.message.reply_text(f"❌ Error: {esc(str(e))}", parse_mode=PARSE)


def _registrar_completado(user, curso_id) -> str:
    """Agrega un usuario a la lista de completados de un curso.
    Devuelve: 'ok', 'ya_estaba' o 'no_existe'."""
    data = load_data()
    c = data["cursos"].get(str(curso_id))
    if not c:
        return "no_existe"
    nombre = user.full_name or (f"@{user.username}" if user.username else str(user.id))
    if nombre in c["completados"]:
        return "ya_estaba"
    c["completados"].append(nombre)
    save_data(data)
    return "ok"


async def completar(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Permite registrarse como que completó un curso."""
    if not ctx.args:
        await update.message.reply_text(
            "❌ Uso: <code>/completar ID</code>", parse_mode=PARSE
        )
        return
    estado = _registrar_completado(update.effective_user, ctx.args[0])
    respuestas = {
        "ok": "✅ Registrado.",
        "ya_estaba": "Ya estabas registrado ✅",
        "no_existe": "❌ Curso no encontrado.",
    }
    await update.message.reply_text(respuestas[estado])


async def completados(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Muestra quién completó cada curso."""
    data = load_data()
    if not data["cursos"]:
        await update.message.reply_text("❌ No hay cursos")
        return

    mensaje = "✅ <b>COMPLETADOS</b>\n\n"
    for cid, c in data["cursos"].items():
        lista = ", ".join(esc(n) for n in c["completados"]) if c["completados"] else "Nadie aún"
        mensaje += f"📚 <b>#{cid} {esc(c['nombre'])}</b>\n{lista}\n\n"
    await update.message.reply_text(mensaje, parse_mode=PARSE)


async def pendientes(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Resumen de tareas pendientes."""
    data = load_data()
    mensaje = "⏳ <b>PENDIENTES</b>\n\n"
    if data["boletines"]:
        mensaje += f"📋 Último boletín: #{data['boletines'][-1]['numero']}\n\n"

    if data["cursos"]:
        mensaje += "📚 <b>Cursos activos:</b>\n"
        for cid, c in data["cursos"].items():
            mensaje += f"• #{cid} {esc(c['nombre'])} — Vence {esc(c['fecha'])}\n"
    else:
        mensaje += "✅ Sin cursos pendientes"
    await update.message.reply_text(mensaje, parse_mode=PARSE)


async def borrar_boletin(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Elimina el último boletín (solo admins)."""
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("❌ No tienes permisos")
        return

    data = load_data()
    if not data["boletines"]:
        await update.message.reply_text("❌ No hay boletines para borrar")
        return

    ultimo = data["boletines"].pop()
    save_data(data)
    try:
        await ctx.bot.delete_message(
            chat_id=update.effective_chat.id, message_id=ultimo["message_id"]
        )
    except Exception as e:
        logger.warning(f"No se pudo borrar el mensaje del boletín: {e}")
    await update.message.reply_text(f"✅ Boletín #{ultimo['numero']} eliminado")


async def borrar_curso(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Elimina un curso (solo admins)."""
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("❌ No tienes permisos")
        return

    if not ctx.args:
        await update.message.reply_text(
            "❌ Uso: <code>/borrar_curso ID</code>", parse_mode=PARSE
        )
        return

    data = load_data()
    curso_id = ctx.args[0]
    if curso_id not in data["cursos"]:
        await update.message.reply_text("❌ Curso no encontrado")
        return

    c = data["cursos"].pop(curso_id)
    save_data(data)
    try:
        if c["message_id"]:
            await ctx.bot.delete_message(
                chat_id=update.effective_chat.id, message_id=c["message_id"]
            )
    except Exception as e:
        logger.warning(f"No se pudo borrar el mensaje del curso: {e}")
    await update.message.reply_text(
        f"✅ Curso '{esc(c['nombre'])}' eliminado", parse_mode=PARSE
    )


# ─── Imágenes: reacción + botón individual ───────────────────────────────────
async def react_heart(ctx, msg):
    """Reacciona con corazón. La reacción NO bloquea el envío del botón:
    se intenta reaccionar y, pase lo que pase, después se manda el botón."""
    for emoji in REACTION_EMOJIS:
        try:
            await ctx.bot.set_message_reaction(
                chat_id=msg.chat_id,
                message_id=msg.message_id,
                reaction=[ReactionTypeEmoji(emoji=emoji)],
            )
            return
        except Exception as e:
            logger.warning(f"No se pudo reaccionar con {emoji}: {e}")


async def on_photo(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Se dispara con fotos o con imágenes enviadas como documento."""
    msg = update.message
    if msg.photo:
        file_id = msg.photo[-1].file_id  # mejor resolución
        tipo = "photo"
    elif msg.document:
        file_id = msg.document.file_id
        tipo = "document"
    else:
        return

    # 1) Reaccionar con corazón (independiente del botón).
    await react_heart(ctx, msg)

    # 2) Registrar la imagen para la descarga masiva.
    data = load_data()
    data["imagenes"].append(
        {
            "file_id": file_id,
            "tipo": tipo,
            "fecha": datetime.now().strftime("%Y%m%d_%H%M%S"),
            "message_id": msg.message_id,
        }
    )
    save_data(data)

    # 3) Botón individual (aparece igual en celular y PC).
    teclado = InlineKeyboardMarkup(
        [[InlineKeyboardButton("⬇️ Descargar / Guardar", callback_data=("dl_menu", file_id))]]
    )
    await msg.reply_text(
        "📷 Imagen recibida.",
        reply_markup=teclado,
        reply_to_message_id=msg.message_id,
    )


# ─── Descarga masiva ─────────────────────────────────────────────────────────
async def descargar_todo(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Ofrece guardar TODAS las imágenes juntas (a carpeta o en un ZIP)."""
    data = load_data()
    n = len(data["imagenes"])
    if n == 0:
        await update.message.reply_text("📭 No hay imágenes registradas todavía.")
        return

    extra = [
        [InlineKeyboardButton("📦 Descargar todo en ZIP", callback_data=("all_zip",))],
        [InlineKeyboardButton(f"🗑️ Vaciar lista ({n})", callback_data=("all_clear",))],
    ]
    await update.message.reply_text(
        f"🖼️ Hay <b>{n}</b> imágenes registradas.\n¿Dónde las guardo?",
        parse_mode=PARSE,
        reply_markup=_folder_keyboard("all_save", extra),
    )


async def _descargar_lista(ctx, imagenes, dest_dir):
    """Descarga una lista de imágenes a dest_dir. Devuelve (ok, fallidas, rutas)."""
    os.makedirs(dest_dir, exist_ok=True)
    ok, fail, rutas = 0, 0, []
    for i, img in enumerate(imagenes, 1):
        try:
            tg_file = await ctx.bot.get_file(img["file_id"])
            ext = os.path.splitext(tg_file.file_path or "")[1] or ".jpg"
            nombre = f"img_{i:03d}_{img.get('fecha', '')}{ext}"
            ruta = os.path.join(dest_dir, nombre)
            await tg_file.download_to_drive(ruta)
            rutas.append(ruta)
            ok += 1
        except Exception as e:
            logger.warning(f"No se pudo descargar imagen {i}: {e}")
            fail += 1
    return ok, fail, rutas


async def save_all_to_folder(ctx, query, folder_key):
    """Guarda todas las imágenes en una subcarpeta del servidor."""
    folder_label = DOWNLOAD_FOLDERS.get(folder_key, "General")
    dest_dir = os.path.join(BASE_DOWNLOAD_DIR, folder_label)
    data = load_data()
    ok, fail, _ = await _descargar_lista(ctx, data["imagenes"], dest_dir)
    texto = f"✅ {ok} imágenes guardadas en:\n<code>{esc(dest_dir)}</code>"
    if fail:
        texto += f"\n❌ {fail} no se pudieron descargar."
    await query.edit_message_text(texto, parse_mode=PARSE)


async def send_all_as_zip(ctx, query):
    """Empaqueta todas las imágenes en un ZIP y lo manda al chat (un solo clic)."""
    data = load_data()
    tmpdir = tempfile.mkdtemp(prefix="imgs_")
    try:
        ok, fail, rutas = await _descargar_lista(ctx, data["imagenes"], tmpdir)
        if not rutas:
            await query.edit_message_text("❌ No se pudo descargar ninguna imagen.")
            return

        zip_name = f"imagenes_{datetime.now():%Y%m%d_%H%M%S}.zip"
        zip_path = os.path.join(tmpdir, zip_name)
        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as z:
            for r in rutas:
                z.write(r, os.path.basename(r))

        size_mb = os.path.getsize(zip_path) / (1024 * 1024)
        if size_mb > MAX_UPLOAD_MB:
            await query.edit_message_text(
                f"⚠️ El ZIP pesa {size_mb:.1f} MB y supera el límite de "
                f"{MAX_UPLOAD_MB} MB de Telegram.\nUsa mejor el guardado por carpeta."
            )
            return

        await query.edit_message_text(f"📦 Enviando ZIP con {ok} imágenes…")
        with open(zip_path, "rb") as f:
            await query.message.reply_document(
                document=f,
                filename=zip_name,
                caption=f"📦 {ok} imágenes" + (f" ({fail} fallaron)" if fail else ""),
            )
    except Exception as e:
        logger.error(f"Error al crear/enviar el ZIP: {e}")
        await query.edit_message_text(f"❌ Error con el ZIP: {esc(str(e))}", parse_mode=PARSE)
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


# ─── Callbacks ───────────────────────────────────────────────────────────────
async def on_callback(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    data = query.data

    # Botones viejos tras reiniciar el bot pierden su data en memoria.
    if not isinstance(data, tuple) or not data:
        await query.answer("Este botón expiró, reenvía la imagen.", show_alert=True)
        return

    action = data[0]
    try:
        if action == "dl_menu":
            await query.answer()
            file_id = data[1]
            extra = [
                [InlineKeyboardButton("📄 Enviar como archivo", callback_data=("dl_doc", file_id))]
            ]
            # Reutilizamos las carpetas, pero la acción individual lleva el file_id.
            items = list(DOWNLOAD_FOLDERS.items())
            filas = []
            for i in range(0, len(items), 2):
                fila = [
                    InlineKeyboardButton(f"📁 {label}", callback_data=("dl_save", file_id, key))
                    for key, label in items[i : i + 2]
                ]
                filas.append(fila)
            filas.extend(extra)
            await query.edit_message_text(
                "¿Dónde quieres guardar la imagen?",
                reply_markup=InlineKeyboardMarkup(filas),
            )

        elif action == "dl_save":
            await query.answer("Guardando…")
            file_id, folder_key = data[1], data[2]
            folder_label = DOWNLOAD_FOLDERS.get(folder_key, "General")
            dest_dir = os.path.join(BASE_DOWNLOAD_DIR, folder_label)
            os.makedirs(dest_dir, exist_ok=True)
            tg_file = await ctx.bot.get_file(file_id)
            ext = os.path.splitext(tg_file.file_path or "")[1] or ".jpg"
            nombre = f"img_{datetime.now():%Y%m%d_%H%M%S}{ext}"
            ruta = os.path.join(dest_dir, nombre)
            await tg_file.download_to_drive(ruta)
            await query.edit_message_text(
                f"✅ Guardada en:\n<code>{esc(ruta)}</code>", parse_mode=PARSE
            )

        elif action == "dl_doc":
            await query.answer()
            await query.message.reply_document(
                document=data[1], caption="📄 Archivo original (sin comprimir)."
            )
            await query.edit_message_text("✅ Enviada como archivo. Descárgala del chat.")

        elif action == "all_save":
            await query.answer("Descargando todas…")
            await save_all_to_folder(ctx, query, data[1])

        elif action == "all_zip":
            await query.answer("Creando ZIP…")
            await send_all_as_zip(ctx, query)

        elif action == "all_clear":
            if not is_admin(query.from_user.id):
                await query.answer("Solo admins pueden vaciar la lista.", show_alert=True)
                return
            d = load_data()
            n = len(d["imagenes"])
            d["imagenes"] = []
            save_data(d)
            await query.answer()
            await query.edit_message_text(f"🗑️ Lista vaciada ({n} imágenes).")

        elif action == "done":
            estado = _registrar_completado(query.from_user, data[1])
            mensajes = {
                "no_existe": ("Curso no encontrado", True),
                "ya_estaba": ("Ya estabas registrado ✅", False),
                "ok": ("¡Registrado! ✅", False),
            }
            texto, alerta = mensajes[estado]
            await query.answer(texto, show_alert=alerta)

        else:
            await query.answer()
    except Exception as e:
        logger.error(f"Error en callback {action}: {e}")
        try:
            await query.answer("Ocurrió un error", show_alert=True)
        except Exception:
            pass


async def on_error(update, ctx: ContextTypes.DEFAULT_TYPE):
    """Captura cualquier excepción no manejada para que el bot no se caiga."""
    logger.error("Excepción no controlada:", exc_info=ctx.error)


# ─── Main ─────────────────────────────────────────────────────────────────────
def main():
    # arbitrary_callback_data permite guardar el file_id en el botón sin el
    # límite de 64 bytes de Telegram (requiere el extra [callback-data]).
    app = Application.builder().token(TOKEN).arbitrary_callback_data(True).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("boletin", boletin))
    app.add_handler(CommandHandler("curso", curso))
    app.add_handler(CommandHandler("completar", completar))
    app.add_handler(CommandHandler("completados", completados))
    app.add_handler(CommandHandler("pendientes", pendientes))
    app.add_handler(CommandHandler("descargar_todo", descargar_todo))
    app.add_handler(CommandHandler("borrar_boletin", borrar_boletin))
    app.add_handler(CommandHandler("borrar_curso", borrar_curso))

    # Imágenes (fotos o documentos imagen)
    app.add_handler(MessageHandler(filters.PHOTO | filters.Document.IMAGE, on_photo))

    # Botones
    app.add_handler(CallbackQueryHandler(on_callback))

    # Manejo global de errores
    app.add_error_handler(on_error)

    logger.info("🚀 Bot Embajadores Volaris iniciado")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
