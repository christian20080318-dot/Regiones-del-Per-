import os
import json
import logging
import unicodedata
import http.server
import socketserver
import threading
from pathlib import Path
from dotenv import load_dotenv
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ContextTypes,
    filters,
)

# Cargar variables de entorno desde .env si existe
load_dotenv()

# Configuración de logging
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
logger = logging.getLogger(__name__)

def iniciar_servidor_salud():
    """Servidor HTTP mínimo para que Render Web Service detecte el puerto abierto y no cancele el deploy."""
    port_str = os.getenv("PORT")
    if not port_str:
        return
    
    port = int(port_str)
    
    class HealthHandler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200)
            self.send_header("Content-Type", "text/plain")
            self.end_headers()
            self.wfile.write(b"OK - Bot de Regiones del Peru activo!")
            
        def log_message(self, format, *args):
            pass

    def run():
        try:
            # Reutilizar puerto de inmediato
            socketserver.TCPServer.allow_reuse_address = True
            with socketserver.TCPServer(("", port), HealthHandler) as httpd:
                logger.info(f"Servidor de salud escuchando en el puerto {port} para Render")
                httpd.serve_forever()
        except Exception as e:
            logger.warning(f"Aviso servidor de salud Render: {e}")

    threading.Thread(target=run, daemon=True).start()

# Rutas de datos
BASE_DIR = Path(__file__).resolve().parent
JSON_PATH = BASE_DIR / "regiones_peru_turismo.json"
IMG_DIR = BASE_DIR / "imagenes_regiones_peru"

# Cargar la información de las 25 regiones
with open(JSON_PATH, "r", encoding="utf-8") as f:
    REGIONES = json.load(f)

def normalizar_texto(texto: str) -> str:
    """Elimina tildes, signos y convierte a minúsculas para comparaciones fáciles."""
    texto = texto.lower().strip()
    texto = unicodedata.normalize("NFKD", texto).encode("ASCII", "ignore").decode("utf-8")
    texto = texto.replace("-", "").replace("_", "").replace(" ", "")
    return texto

# Crear un mapa rápido de búsqueda por alias
REGIONES_MAP = {}
for r in REGIONES:
    id_clean = normalizar_texto(r["region"])
    REGIONES_MAP[id_clean] = r
    # Alias adicionales
    if "callao" in id_clean:
        REGIONES_MAP["callao"] = r
    if "sanmartin" in id_clean:
        REGIONES_MAP["sanmartin"] = r
        REGIONES_MAP["san_martin"] = r
    if "madrededios" in id_clean:
        REGIONES_MAP["madrededios"] = r
        REGIONES_MAP["madre_de_dios"] = r
    if "lalibertad" in id_clean:
        REGIONES_MAP["lalibertad"] = r
        REGIONES_MAP["la_libertad"] = r

def construir_mensaje_region(r: dict) -> str:
    """Genera el texto descriptivo formateado en Markdown para la región."""
    return (
        f"🇵🇪 *{r['region'].upper()}*\n"
        f"🏛 *Capital / Sede:* {r['capital']}\n"
        f"📍 *Atractivo principal:* {r['atractivo_principal']}\n\n"
        f"📖 *Reseña turística:*\n{r['descripcion']}"
    )

async def enviar_region(update: Update, r: dict):
    """Envía la imagen local de la región con su descripción como pie de foto (caption)."""
    img_path = BASE_DIR / r["ruta_local"]
    mensaje = construir_mensaje_region(r)

    # Si el texto es largo para un caption (límite de Telegram es 1024 caracteres en caption), se maneja
    caption = mensaje if len(mensaje) <= 1020 else mensaje[:1015] + "..."

    chat = update.effective_chat
    if img_path.exists():
        with open(img_path, "rb") as foto:
            await chat.send_photo(photo=foto, caption=caption, parse_mode="Markdown")
    else:
        await chat.send_message(text=mensaje, parse_mode="Markdown")

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Comando /start: Mensaje de bienvenida y opciones."""
    nombre = update.effective_user.first_name if update.effective_user else "Viajero"
    texto = (
        f"¡Hola, {nombre}! 🇵🇪 Bienvenido al *Bot Turístico de las 25 Regiones del Perú*.\n\n"
        f"Aquí puedes explorar los mejores atractivos turísticos, fotografías y descripciones "
        f"de los 24 departamentos y la Provincia Constitucional del Callao.\n\n"
        f"📌 *¿Cómo usar el bot?*\n"
        f"1️⃣ Presiona /regiones para ver el menú interactivo con botones.\n"
        f"2️⃣ O escribe directamente el nombre o comando de una región, por ejemplo:\n"
        f"   • /cusco o escribe `Cusco`\n"
        f"   • /arequipa o escribe `Arequipa`\n"
        f"   • /loreto o escribe `Loreto`\n"
        f"   • /callao o escribe `Callao`\n\n"
        f"3️⃣ Presiona /ayuda para ver todos los comandos disponibles."
    )
    
    # Botón directo para abrir el menú de regiones
    keyboard = [[InlineKeyboardButton("🗺️ Ver todas las regiones", callback_data="menu_page_0")]]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await update.message.reply_text(texto, parse_mode="Markdown", reply_markup=reply_markup)

async def ayuda(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Comando /ayuda: Lista todos los comandos."""
    comandos = [f"/{normalizar_texto(r['region'])} - {r['region']}" for r in REGIONES]
    texto = (
        "🧭 *Comandos disponibles de las 25 regiones:*\n\n"
        + "\n".join(comandos)
        + "\n\n💡 _También puedes escribir cualquier región en el chat sin el slash (ej. 'Puno', 'Tumbes')._"
    )
    await update.message.reply_text(texto, parse_mode="Markdown")

def crear_teclado_regiones(pagina: int = 0) -> InlineKeyboardMarkup:
    """Crea botones interactivos paginados para las 25 regiones (9 por página)."""
    por_pagina = 9
    inicio = pagina * por_pagina
    fin = inicio + por_pagina
    sublista = REGIONES[inicio:fin]

    botones = []
    fila = []
    for r in sublista:
        clave = normalizar_texto(r["region"])
        fila.append(InlineKeyboardButton(r["region"], callback_data=f"reg_{clave}"))
        if len(fila) == 3:
            botones.append(fila)
            fila = []
    if fila:
        botones.append(fila)

    # Botones de navegación
    total_paginas = (len(REGIONES) + por_pagina - 1) // por_pagina
    fila_nav = []
    if pagina > 0:
        fila_nav.append(InlineKeyboardButton("⬅️ Anterior", callback_data=f"menu_page_{pagina - 1}"))
    if pagina < total_paginas - 1:
        fila_nav.append(InlineKeyboardButton("Siguiente ➡️", callback_data=f"menu_page_{pagina + 1}"))

    if fila_nav:
        botones.append(fila_nav)

    return InlineKeyboardMarkup(botones)

async def regiones_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Comando /regiones: Muestra el menú de botones."""
    teclado = crear_teclado_regiones(0)
    await update.message.reply_text(
        "🇵🇪 *Selecciona una región para ver su foto y reseña turística:*",
        parse_mode="Markdown",
        reply_markup=teclado
    )

async def callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Maneja las pulsaciones de botones interactivos."""
    query = update.callback_query
    await query.answer()

    data = query.data
    if data.startswith("menu_page_"):
        pagina = int(data.split("_")[2])
        teclado = crear_teclado_regiones(pagina)
        await query.edit_message_text(
            f"🇵🇪 *Selecciona una región (Página {pagina + 1}/3):*",
            parse_mode="Markdown",
            reply_markup=teclado
        )
    elif data.startswith("reg_"):
        clave = data.split("_", 1)[1]
        r = REGIONES_MAP.get(clave)
        if r:
            img_path = BASE_DIR / r["ruta_local"]
            mensaje = construir_mensaje_region(r)
            caption = mensaje if len(mensaje) <= 1020 else mensaje[:1015] + "..."

            if img_path.exists():
                with open(img_path, "rb") as foto:
                    await query.message.chat.send_photo(
                        photo=foto, caption=caption, parse_mode="Markdown"
                    )
            else:
                await query.message.chat.send_message(text=mensaje, parse_mode="Markdown")

async def comando_region_dinamico(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Maneja los comandos tipo /cusco, /arequipa, etc."""
    comando = update.message.text.split()[0].replace("/", "")
    clave = normalizar_texto(comando)
    r = REGIONES_MAP.get(clave)
    if r:
        await enviar_region(update, r)
    else:
        await update.message.reply_text(
            "Región no encontrada. Escribe /regiones para ver la lista completa."
        )

async def mensaje_texto_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Detecta si el usuario escribió el nombre de una región en texto libre."""
    texto_usuario = normalizar_texto(update.message.text)
    
    # Buscar si alguna región está mencionada en el texto
    region_encontrada = None
    for clave, r in REGIONES_MAP.items():
        if clave in texto_usuario:
            region_encontrada = r
            break

    if region_encontrada:
        await enviar_region(update, region_encontrada)
    else:
        await update.message.reply_text(
            f"No reconocí esa región. Prueba escribiendo el nombre de una región (ej. *Cusco*, *Áncash*, *Ica*) "
            f"o usa el comando /regiones.",
            parse_mode="Markdown"
        )

def main():
    # Obtener el token de la variable de entorno
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    if not token or token == "TU_TOKEN_AQUI":
        token = input("Por favor ingresa tu Token de Telegram BotFather: ").strip()

    if not token:
        print("Error: No se proporcionó ningún token de Telegram.")
        return

    # Iniciar servidor web si Render asignó la variable PORT
    iniciar_servidor_salud()

    print("Iniciando Bot de las 25 Regiones del Perú...")
    app = ApplicationBuilder().token(token).build()

    # Comandos básicos
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("ayuda", ayuda))
    app.add_handler(CommandHandler("help", ayuda))
    app.add_handler(CommandHandler("regiones", regiones_menu))

    # Handlers para cada región como comando directo (/cusco, /lima, etc.)
    for r in REGIONES:
        cmd = normalizar_texto(r["region"])
        app.add_handler(CommandHandler(cmd, comando_region_dinamico))
        # Alias comunes sin tildes o abreviados
        if "callao" in cmd:
            app.add_handler(CommandHandler("callao", comando_region_dinamico))

    # Botones inline
    app.add_handler(CallbackQueryHandler(callback_handler))

    # Mensajes de texto normales
    app.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), mensaje_texto_handler))

    print("¡Bot en ejecución! Presiona Ctrl + C en la terminal para detenerlo.")
    app.run_polling()

if __name__ == "__main__":
    main()
