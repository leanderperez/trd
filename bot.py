import asyncio
import logging
from telegram import Update
from telegram.ext import ApplicationBuilder, ContextTypes, CommandHandler, MessageHandler, filters

# --- CONFIGURACIÓN ---
TOKEN = '8520487605:AAFEUVvDIT5nI_iqpypXX_gpRhlO191mqyU'
ADMIN_ID = 610413875  # <--- REEMPLAZA CON TU ID DE TELEGRAM
# ---------------------

# Estructura en RAM
rooms = {} # "nombre": {"pass": "x", "members": [id1, id2], "pending": [], "notifs": {id: [msg_ids]}}
user_to_room = {}

logging.basicConfig(level=logging.INFO)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🔐 **Pasarela Secreta Pro**\nUsa `/join sala clave` para entrar.")

async def join(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.chat_id
    try:
        room_name, password = context.args[0], context.args[1]
    except:
        await update.message.reply_text("Uso: /join <sala> <clave>")
        return

    if room_name not in rooms:
        rooms[room_name] = {"password": password, "members": [], "pending": [], "notifs": {}}

    room = rooms[room_name]

    # 1. Validar Contraseña
    if room["password"] != password:
        await update.message.reply_text("❌ Clave incorrecta.")
        return

    # 2. Validar Límite de 2 usuarios
    if user_id not in room["members"] and len(room["members"]) >= 2:
        await update.message.reply_text("🚫 Esta sala está llena (máximo 2 personas).")
        return

    # 3. Entrar a la sala
    if user_id not in room["members"]:
        room["members"].append(user_id)
        room["notifs"][user_id] = []
    
    user_to_room[user_id] = room_name
    await update.message.reply_text(f"✅ Has entrado a '{room_name}'.")

    # 4. Limpiar notificaciones previas de "Tienes un mensaje"
    if user_id in room["notifs"]:
        for m_id in room["notifs"][user_id]:
            try: await context.bot.delete_message(chat_id=user_id, message_id=m_id)
            except: pass
        room["notifs"][user_id] = []

    # 5. Entregar mensajes/media pendientes
    if room["pending"]:
        for item in room["pending"]:
            if item["sender"] != user_id:
                await deliver_content(context, user_id, item)
        # Limpiar pendientes una vez entregados
        room["pending"] = [i for i in room["pending"] if i["sender"] == user_id]

async def deliver_content(context, chat_id, item):
    """Entrega contenido y programa borrado si no es el ADMIN"""
    msg_type = item["type"]
    content = item["content"]
    caption = "📩 **Mensaje Secreto**"
    
    sent = None
    if msg_type == "text":
        sent = await context.bot.send_message(chat_id=chat_id, text=f"{caption}\n{content}")
    elif msg_type == "photo":
        sent = await context.bot.send_photo(chat_id=chat_id, photo=content, caption=caption)
    elif msg_type == "video":
        sent = await context.bot.send_video(chat_id=chat_id, video=content, caption=caption)

    # Si el receptor NO es el Admin, borrar a los 20s
    if chat_id != ADMIN_ID:
        asyncio.create_task(delete_after_delay(context, chat_id, sent.message_id, 20))

async def handle_incoming(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.chat_id
    if user_id not in user_to_room:
        await update.message.reply_text("⚠️ Únete a una sala primero.")
        return

    room_name = user_to_room[user_id]
    room = rooms[room_name]
    
    # Identificar tipo de contenido
    content_item = {"sender": user_id}
    if update.message.text:
        content_item.update({"type": "text", "content": update.message.text})
    elif update.message.photo:
        content_item.update({"type": "photo", "content": update.message.photo[-1].file_id})
    elif update.message.video:
        content_item.update({"type": "video", "content": update.message.video.file_id})
    else:
        return # Otros tipos no soportados

    # Borrar mensaje original del emisor
    await update.message.delete()

    # Guardar en pendientes
    room["pending"].append(content_item)

    # Notificar a otros miembros
    others = [m for m in room["members"] if m != user_id]
    for m_id in others:
        n_msg = await context.bot.send_message(chat_id=m_id, text=f"🔔 Nuevo mensaje en '{room_name}'. Entra para verlo.")
        room["notifs"][m_id].append(n_msg.message_id)

async def delete_after_delay(context, chat_id, message_id, delay):
    await asyncio.sleep(delay)
    try: await context.bot.delete_message(chat_id=chat_id, message_id=message_id)
    except: pass

if __name__ == '__main__':
    app = ApplicationBuilder().token(TOKEN).build()
    app.add_handler(CommandHandler('start', start))
    app.add_handler(CommandHandler('join', join))
    app.add_handler(MessageHandler((filters.TEXT | filters.PHOTO | filters.VIDEO) & (~filters.COMMAND), handle_incoming))
    app.run_polling()