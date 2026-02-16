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
monitor_active = {} # {admin_id: True/False}

logging.basicConfig(level=logging.INFO)

# Botones
BTN_ENTRAR = '🔑 Entrar a Sala'
BTN_SALIR = '🚪 Salir de la Sala'
BTN_MONITOR = '🕵️ Monitor: ON/OFF'

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    
    # Teclado dinámico: Si es Admin, ve el botón de Monitor
    keyboard = [[BTN_ENTRAR]]
    if user_id == ADMIN_ID:
        keyboard.append([BTN_MONITOR])
    
    reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
    await update.message.reply_text("🔐 **Pasarela Pro**", reply_markup=reply_markup)

async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.chat_id
    text = update.message.text

    # LÓGICA DE MONITOR (Solo para el Admin)
    if text == BTN_MONITOR and user_id == ADMIN_ID:
        current = monitor_active.get(user_id, False)
        monitor_active[user_id] = not current
        estado = "ACTIVADO" if monitor_active[user_id] else "DESACTIVADO"
        msg = await update.message.reply_text(f"📡 Modo Monitor: **{estado}**")
        asyncio.create_task(delete_after_delay(context, user_id, msg.message_id, 3))
        return

    # SALIR DE SALA
    if text == BTN_SALIR:
        if user_id in user_to_room:
            room_name = user_to_room.pop(user_id)
            if room_name in rooms and user_id in rooms[room_name]["members"]:
                rooms[room_name]["members"].remove(user_id)
            
            # Volver al teclado de inicio (con monitor si es admin)
            keyboard = [[BTN_ENTRAR]]
            if user_id == ADMIN_ID: keyboard.append([BTN_MONITOR])
            reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
            
            msg = await update.message.reply_text("👋 Salida segura.", reply_markup=reply_markup)
            asyncio.create_task(delete_after_delay(context, user_id, msg.message_id, 3))
        return

    # ENTRAR A SALA
    if text == BTN_ENTRAR:
        waiting_for_key.add(user_id)
        await update.message.reply_text("Escriba la **Clave**:", reply_markup=ReplyKeyboardRemove())
        return

    # PROCESAR CLAVE
    if user_id in waiting_for_key:
        room_key = text
        waiting_for_key.remove(user_id)
        
        if room_key not in rooms:
            rooms[room_key] = {"members": [], "pending": []}
        
        room = rooms[room_key]
        if user_id not in room["members"] and len(room["members"]) >= 2:
            await update.message.reply_text("🚫 Sala llena.")
            return

        if user_id not in room["members"]: room["members"].append(user_id)
        user_to_room[user_id] = room_key
        
        reply_markup = ReplyKeyboardMarkup([[BTN_SALIR]], resize_keyboard=True)
        msg = await update.message.reply_text(f"✅ En sala: `{room_key}`", reply_markup=reply_markup)
        asyncio.create_task(delete_after_delay(context, user_id, msg.message_id, 3))

        # Entrega de pendientes (Modificado para que el Admin pueda probar solo)
        if room["pending"]:
            for item in list(room["pending"]):
                # Si eres admin probando solo, permitimos ver tus propios msjs
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
    
    content_item = {"sender": user_id, "user_name": update.effective_user.first_name}
    if update.message.text:
        content_item.update({"type": "text", "content": update.message.text})
    elif update.message.photo:
        content_item.update({"type": "photo", "content": update.message.photo[-1].file_id})
    elif update.message.video:
        content_item.update({"type": "video", "content": update.message.video.file_id})
    else: return

    # Borrado emisor (2s)
    asyncio.create_task(delete_after_delay(context, user_id, update.message.message_id, 2))
    room["pending"].append(content_item)

    # MONITOR: Notificar al admin en tiempo real si el modo está ON
    if monitor_active.get(ADMIN_ID, False) and user_id != ADMIN_ID:
        await context.bot.send_message(
            chat_id=ADMIN_ID, 
            text=f"🕵️ **Monitor [{room_name}]:** {content_item['user_name']} envió un {content_item['type']}."
        )

    # Notificar a otros
    others = [m for m in room["members"] if m != user_id]
    for m_id in others:
        n_msg = await context.bot.send_message(chat_id=m_id, text="🔔 Nuevo mensaje.")
        asyncio.create_task(delete_after_delay(context, m_id, n_msg.message_id, 3))

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

        # Borrado receptor (10s) - Admin no borra multimedia
        if not (chat_id == ADMIN_ID and msg_type in ["photo", "video"]):
            asyncio.create_task(delete_after_delay(context, chat_id, sent.message_id, 10))
        
        # Se elimina de pendientes tras entregar al destinatario real
        if item["sender"] != chat_id:
            if item in rooms[room_name]["pending"]:
                rooms[room_name]["pending"].remove(item)
    except: pass

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