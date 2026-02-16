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
monitor_active = {}

logging.basicConfig(level=logging.INFO)

# Definición de Botones
BTN_ENTRAR = '🔑 Entrar a Sala'
BTN_SALIR = '🚪 Salir de la Sala'
BTN_MONITOR = '🕵️ Monitor: ON/OFF'

# Teclados constantes
KEYBOARD_INICIO = [[BTN_ENTRAR]]
KEYBOARD_SALA = [[BTN_SALIR]]

async def delete_msg(context, chat_id, message_id, delay=0):
    if delay > 0: await asyncio.sleep(delay)
    try: await context.bot.delete_message(chat_id=chat_id, message_id=message_id)
    except: pass

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    asyncio.create_task(delete_msg(context, user_id, update.message.message_id))
    
    kb = KEYBOARD_INICIO.copy()
    if user_id == ADMIN_ID: kb.append([BTN_MONITOR])
    
    # input_field_placeholder mantiene un texto en la barra de escritura
    markup = ReplyKeyboardMarkup(kb, resize_keyboard=True, is_persistent=True, input_field_placeholder="Seleccione una opción")
    await update.message.reply_text("🔐 **Pasarela Pro**", reply_markup=markup)

async def salir_comando(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """ Comando de emergencia /salir por si fallan los botones """
    user_id = update.effective_user.id
    await ejecutar_salida(user_id, context, update)

async def ejecutar_salida(user_id, context, update):
    if user_id in user_to_room:
        room_name = user_to_room.pop(user_id)
        if room_name in rooms and user_id in rooms[room_name]["members"]:
            rooms[room_name]["members"].remove(user_id)
        
        kb = KEYBOARD_INICIO.copy()
        if user_id == ADMIN_ID: kb.append([BTN_MONITOR])
        markup = ReplyKeyboardMarkup(kb, resize_keyboard=True, is_persistent=True)
        
        msg = await context.bot.send_message(chat_id=user_id, text="👋 Sesión cerrada y sala liberada.", reply_markup=markup)
        asyncio.create_task(delete_msg(context, user_id, msg.message_id, 3))

async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.chat_id
    text = update.message.text

    # BOTÓN SALIR O COMANDO /SALIR
    if text == BTN_SALIR:
        asyncio.create_task(delete_msg(context, user_id, update.message.message_id))
        await ejecutar_salida(user_id, context, update)
        return

    # BOTÓN MONITOR
    if text == BTN_MONITOR and user_id == ADMIN_ID:
        asyncio.create_task(delete_msg(context, user_id, update.message.message_id))
        current = monitor_active.get(user_id, False)
        monitor_active[user_id] = not current
        msg = await update.message.reply_text(f"📡 Monitor: {'ON' if monitor_active[user_id] else 'OFF'}")
        asyncio.create_task(delete_msg(context, user_id, msg.message_id, 3))
        return

    # BOTÓN ENTRAR
    if text == BTN_ENTRAR:
        asyncio.create_task(delete_msg(context, user_id, update.message.message_id))
        waiting_for_key.add(user_id)
        msg = await update.message.reply_text("Escriba la **Clave**:", reply_markup=ReplyKeyboardRemove())
        asyncio.create_task(delete_msg(context, user_id, msg.message_id, 10))
        return

    # INGRESO DE CLAVE
    if user_id in waiting_for_key:
        room_key = text
        waiting_for_key.remove(user_id)
        asyncio.create_task(delete_msg(context, user_id, update.message.message_id))
        
        if room_key not in rooms: rooms[room_key] = {"members": [], "pending": []}
        room = rooms[room_key]
        
        if user_id not in room["members"] and len(room["members"]) >= 2:
            msg = await update.message.reply_text("🚫 Sala llena.")
            asyncio.create_task(delete_msg(context, user_id, msg.message_id, 3))
            return

        user_to_room[user_id] = room_key
        if user_id not in room["members"]: room["members"].append(user_id)
        
        markup = ReplyKeyboardMarkup(KEYBOARD_SALA, resize_keyboard=True, is_persistent=True)
        msg = await update.message.reply_text(f"✅ Acceso a `{room_key}`", reply_markup=markup)
        asyncio.create_task(delete_msg(context, user_id, msg.message_id, 3))

        for item in list(room["pending"]):
            if item["sender"] != user_id or user_id == ADMIN_ID:
                await deliver_content(context, user_id, item, room_key)
        return

    # MENSAJES DE CHAT
    if user_id in user_to_room:
        await process_message(update, context)

async def process_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.chat_id
    room_name = user_to_room[user_id]
    room = rooms[room_name]
    
    # Borrar mensaje del usuario (2s)
    asyncio.create_task(delete_msg(context, user_id, update.message.message_id, 2))
    
    content_item = {"sender": user_id, "user_name": update.effective_user.first_name}
    if update.message.text: content_item.update({"type": "text", "content": update.message.text})
    elif update.message.photo: content_item.update({"type": "photo", "content": update.message.photo[-1].file_id})
    elif update.message.video: content_item.update({"type": "video", "content": update.message.video.file_id})
    else: return

    room["pending"].append(content_item)

    # Monitor Admin
    if monitor_active.get(ADMIN_ID, False) and user_id != ADMIN_ID:
        await context.bot.send_message(chat_id=ADMIN_ID, text=f"🕵️ [{room_name}]: Actividad.")

    # Notificar a otros y REFORZAR TECLADO DE SALIDA
    others = [m for m in room["members"] if m != user_id]
    for m_id in others:
        markup = ReplyKeyboardMarkup(KEYBOARD_SALA, resize_keyboard=True, is_persistent=True)
        n_msg = await context.bot.send_message(chat_id=m_id, text="🔔 Mensaje pendiente.", reply_markup=markup)
        asyncio.create_task(delete_msg(context, m_id, n_msg.message_id, 4))

async def deliver_content(context, chat_id, item, room_name):
    msg_type, content = item["type"], item["content"]
    markup = ReplyKeyboardMarkup(KEYBOARD_SALA, resize_keyboard=True, is_persistent=True)
    
    try:
        if msg_type == "text":
            sent = await context.bot.send_message(chat_id=chat_id, text=f"📩:\n{content}", reply_markup=markup)
        elif msg_type == "photo":
            sent = await context.bot.send_photo(chat_id=chat_id, photo=content, reply_markup=markup)
        elif msg_type == "video":
            sent = await context.bot.send_video(chat_id=chat_id, video=content, reply_markup=markup)

        if not (chat_id == ADMIN_ID and msg_type in ["photo", "video"]):
            asyncio.create_task(delete_msg(context, chat_id, sent.message_id, 10))
        
        if item["sender"] != chat_id:
            if item in rooms[room_name]["pending"]: rooms[room_name]["pending"].remove(item)
    except: pass

if __name__ == '__main__':
    app = ApplicationBuilder().token(TOKEN).build()
    app.add_handler(CommandHandler('start', start))
    app.add_handler(CommandHandler('salir', salir_comando)) # Comando de emergencia
    app.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), handle_text))
    app.add_handler(MessageHandler(filters.PHOTO | filters.VIDEO, process_message))
    app.run_polling()