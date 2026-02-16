import asyncio
import logging
from telegram import Update, ReplyKeyboardMarkup, ReplyKeyboardRemove
from telegram.ext import ApplicationBuilder, ContextTypes, CommandHandler, MessageHandler, filters

# --- CONFIGURACIÓN ---
TOKEN = 'TU_TOKEN_AQUI'
ADMIN_ID = 610413875 
# ---------------------

rooms = {} 
user_to_room = {}
waiting_for_key = set()

logging.basicConfig(level=logging.INFO)

# Teclados predefinidos
START_KEYBOARD = [['🔑 Entrar a Sala']]
IN_ROOM_KEYBOARD = [['🚪 Salir de la Sala']]

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    reply_markup = ReplyKeyboardMarkup(START_KEYBOARD, resize_keyboard=True)
    await update.message.reply_text(
        "🔐 **Bienvenido a la Pasarela Secreta**\nPulse el botón para acceder.",
        reply_markup=reply_markup
    )

async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.chat_id
    text = update.message.text

    # BOTÓN: SALIR DE LA SALA
    if text == "🚪 Salir de la Sala":
        if user_id in user_to_room:
            room_name = user_to_room.pop(user_id)
            # (Opcional) Podrías eliminarlo de room["members"] si quieres que la sala quede libre
            if room_name in rooms and user_id in rooms[room_name]["members"]:
                rooms[room_name]["members"].remove(user_id)
            
            reply_markup = ReplyKeyboardMarkup(START_KEYBOARD, resize_keyboard=True)
            await update.message.reply_text("👋 Has salido de la sala de forma segura.", reply_markup=reply_markup)
        return

    # BOTÓN: ENTRAR A SALA
    if text == "🔑 Entrar a Sala":
        waiting_for_key.add(user_id)
        await update.message.reply_text("Escriba la **Clave de la Sala**:", reply_markup=ReplyKeyboardRemove())
        return

    # LÓGICA DE INGRESO POR CLAVE
    if user_id in waiting_for_key:
        room_key = text
        waiting_for_key.remove(user_id)
        
        if room_key not in rooms:
            rooms[room_key] = {"members": [], "pending": [], "notifs": {}}
        
        room = rooms[room_key]

        if user_id not in room["members"] and len(room["members"]) >= 2:
            reply_markup = ReplyKeyboardMarkup(START_KEYBOARD, resize_keyboard=True)
            await update.message.reply_text("🚫 Sala llena.", reply_markup=reply_markup)
            return

        if user_id not in room["members"]:
            room["members"].append(user_id)
            room["notifs"][user_id] = []
        
        user_to_room[user_id] = room_key
        
        # Mostrar botón de salir al entrar con éxito
        reply_markup = ReplyKeyboardMarkup(IN_ROOM_KEYBOARD, resize_keyboard=True)
        await update.message.reply_text(
            f"✅ Conectado a: `{room_key}`\nLos mensajes que envíes se borrarán en 2s.\nLos que recibas, en 10s.",
            reply_markup=reply_markup
        )

        if room["pending"]:
            for item in list(room["pending"]):
                if item["sender"] != user_id:
                    await deliver_content(context, user_id, item)
            room["pending"] = [i for i in room["pending"] if i["sender"] == user_id]
        return

    # MENSAJES DENTRO DE LA SALA
    if user_id in user_to_room:
        await process_message(update, context)
    else:
        await update.message.reply_text("⚠️ Use el menú para comenzar.")

async def process_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.chat_id
    room_name = user_to_room[user_id]
    room = rooms[room_name]
    
    content_item = {"sender": user_id}
    
    if update.message.text:
        content_item.update({"type": "text", "content": update.message.text})
    elif update.message.photo:
        content_item.update({"type": "photo", "content": update.message.photo[-1].file_id})
    elif update.message.video:
        content_item.update({"type": "video", "content": update.message.video.file_id})
    else:
        return

    # Borrado del emisor (2 segundos)
    asyncio.create_task(delete_after_delay(context, user_id, update.message.message_id, 2))
    room["pending"].append(content_item)

    others = [m for m in room["members"] if m != user_id]
    for m_id in others:
        n_msg = await context.bot.send_message(chat_id=m_id, text=f"🔔 Nuevo mensaje en la sala.")
        if m_id not in room["notifs"]: room["notifs"][m_id] = []
        room["notifs"][m_id].append(n_msg.message_id)

async def deliver_content(context, chat_id, item, room_name):
    msg_type, content = item["type"], item["content"]
    sent = None
    try:
        if msg_type == "text":
            sent = await context.bot.send_message(chat_id=chat_id, text=f"📩 **Mensaje:**\n{content}")
        elif msg_type == "photo":
            sent = await context.bot.send_photo(chat_id=chat_id, photo=content, caption="📩 **Foto**")
        elif msg_type == "video":
            sent = await context.bot.send_video(chat_id=chat_id, video=content, caption="📩 **Video**")

        # 1. Programar borrado en el chat de Telegram (10 segundos)
        if not (chat_id == ADMIN_ID and msg_type in ["photo", "video"]):
            asyncio.create_task(delete_after_delay(context, chat_id, sent.message_id, 10))
            
        # 2. ELIMINAR DE LA MEMORIA DEL BOT
        # Al terminar esta función, el mensaje ya fue entregado y se elimina de la lista 'pending'
        if item in rooms[room_name]["pending"]:
            rooms[room_name]["pending"].remove(item)
            
    except Exception as e:
        logging.error(f"Error en entrega: {e}")

async def delete_after_delay(context, chat_id, message_id, delay):
    await asyncio.sleep(delay)
    try: await context.bot.delete_message(chat_id=chat_id, message_id=message_id)
    except: pass

if __name__ == '__main__':
    app = ApplicationBuilder().token(TOKEN).build()
    app.add_handler(CommandHandler('start', start))
    app.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), handle_text))
    app.add_handler(MessageHandler(filters.PHOTO | filters.VIDEO, process_message))
    app.run_polling()