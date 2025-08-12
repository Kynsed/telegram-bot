import requests
import base64
import time
from io import BytesIO
from pathlib import Path
from PIL import Image
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    ContextTypes,
    JobQueue,
)

# Credenciais
TELEGRAM_BOT_TOKEN = "8451339428:AAGYn6fEoP1AY_o6WcYJvdrxPJj9fXRaoVk"
PUSHINPAY_API_TOKEN = "42244|OS4YkUONt9ulRypD8sX0juRAvHHvQCDuwcwTEjXb4367fbd2"
PUSHINPAY_CREATE_PIX_URL = "https://api.pushinpay.com.br/api/pix/cashIn"
PUSHINPAY_CHECK_PIX_URL = "https://api.pushinpay.com.br/api/transactions/{ID}"

# Arquivos de mídia
BASE_DIR = Path(__file__).parent
AUDIO_PATH = BASE_DIR / "telegram_audio.ogg"
VIDEO_PATH = BASE_DIR / "WhatsApp Video 2025-08-07 at 21.48.59.mp4"

# Mensagens
WELCOME_MESSAGE = (
    "✨ Bem-vindo aos conteudinhos da Julia ✨\n\n"
    "Confira os meus vídeos mais quentes,\n"
    "sem nenhum corte, mostrando tudo bem\n"
    "de pertinho pra você gozar gostoso\n"
    "comigo 🔥💋"
)

MENSAGEM_PLANO = (
    "🌟 Você selecionou o seguinte plano:\n\n"
    "🎁 Plano: PLANO VIP\n"
    "💰 Valor: R$39,90\n\n"
    "💠 Pague via Pix Copia e Cola (ou QR Code em alguns bancos)\n"
    "👇 Toque na chave Pix abaixo para copiá-la"
)

LINK_PREMIUM = "https://drive.google.com/drive/folders/15Qsy3EZmkLYhgxRfhshVtG9T9RMoqy3d?usp=drive_link"

# Cooldown por usuário
COOLDOWN_SEGUNDOS = 60
cooldown_tracker = {}
transaction_tracker = {}

# Função para redimensionar QR Code
def redimensionar_qr(base64_str, tamanho=300):
    b64 = base64_str.split(",", 1)[-1]
    img_bytes = base64.b64decode(b64)
    img = Image.open(BytesIO(img_bytes))
    img = img.resize((tamanho, tamanho), Image.LANCZOS)
    buffer = BytesIO()
    img.save(buffer, format="PNG")
    buffer.seek(0)
    return buffer

# Comando /start
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id

    if AUDIO_PATH.exists():
        with AUDIO_PATH.open("rb") as f:
            await context.bot.send_audio(chat_id=chat_id, audio=f)

    if VIDEO_PATH.exists():
        with VIDEO_PATH.open("rb") as f:
            await context.bot.send_video(chat_id=chat_id, video=f)

    keyboard = [[InlineKeyboardButton("PLANO VIP PADRÃO POR R$39,90", callback_data="gerar_pix")]]
    await context.bot.send_message(chat_id=chat_id, text=WELCOME_MESSAGE, reply_markup=InlineKeyboardMarkup(keyboard))

# Geração do Pix
async def gerar_pix(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = query.from_user.id
    chat_id = query.message.chat_id
    now = time.time()

    if user_id in cooldown_tracker:
        tempo_passado = now - cooldown_tracker[user_id]
        if tempo_passado < COOLDOWN_SEGUNDOS:
            restante = int(COOLDOWN_SEGUNDOS - tempo_passado)
            await query.answer()
            await query.message.reply_text(f"⏳ Aguarde {restante} segundos antes de gerar uma nova chave Pix.")
            return

    cooldown_tracker[user_id] = now
    await query.answer()

    headers = {
        "Authorization": f"Bearer {PUSHINPAY_API_TOKEN}",
        "Accept": "application/json",
        "Content-Type": "application/json"
    }

    payload = {
        "value": 50,
        "webhook_url": "https://seu-site.com",
        "split_rules": []
    }

    try:
        resp = requests.post(PUSHINPAY_CREATE_PIX_URL, json=payload, headers=headers, timeout=20)
        resp.raise_for_status()
        data = resp.json()
    except Exception as e:
        await query.message.reply_text(f"Erro ao criar PIX: {e}")
        return

    chave_pix = data.get("qr_code")
    qr_b64 = data.get("qr_code_base64")
    transaction_id = data.get("id")

    if transaction_id:
        transaction_tracker[user_id] = transaction_id

        # ✅ Inicia verificação automática a cada 10 segundos
        context.job_queue.run_repeating(
            verificar_pagamento_job,
            interval=10,
            first=10,
            data={"user_id": user_id, "chat_id": chat_id, "transaction_id": transaction_id},
            name=f"verificacao_{user_id}"
        )

    if qr_b64:
        try:
            qr_img = redimensionar_qr(qr_b64, tamanho=300)
            await query.message.reply_photo(photo=qr_img, filename="pix_qrcode.png")
        except Exception as e:
            await query.message.reply_text(f"Erro ao processar QR Code: {e}")

    if chave_pix:
        await query.message.reply_text(MENSAGEM_PLANO)
        await query.message.reply_text(f"`{chave_pix}`", parse_mode="Markdown")

        keyboard = [[InlineKeyboardButton("STATUS DO PAGAMENTO", callback_data="verificar_pagamento")]]
        await query.message.reply_text("🔍 Verifique o status do pagamento:", reply_markup=InlineKeyboardMarkup(keyboard))
    else:
        await query.message.reply_text("PIX criado, mas não recebi a chave Pix na resposta.")

# 🔄 Verificação automática em background
async def verificar_pagamento_job(context: ContextTypes.DEFAULT_TYPE):
    transaction_id = context.job.data["transaction_id"]
    chat_id = context.job.data["chat_id"]
    user_id = context.job.data["user_id"]

    url = PUSHINPAY_CHECK_PIX_URL.replace("{ID}", transaction_id)
    headers = {
        "Authorization": f"Bearer {PUSHINPAY_API_TOKEN}",
        "Accept": "application/json",
        "Content-Type": "application/json"
    }

    try:
        resp = requests.get(url, headers=headers, timeout=20)
        if resp.status_code != 200:
            print(f"[Verificação] Status HTTP {resp.status_code}")
            return

        data = resp.json()
        status = data.get("status")
        print(f"[Verificação] Transação {transaction_id} → {status}")

        if status == "paid":
            await context.bot.send_message(chat_id=chat_id, text="✅ Pagamento aprovado!")
            await context.bot.send_message(chat_id=chat_id, text=f"🎁 Conteúdo liberado:\n{LINK_PREMIUM}")

            # Remove o job
            job_name = f"verificacao_{user_id}"
            jobs = context.job_queue.get_jobs_by_name(job_name)
            for job in jobs:
                job.schedule_removal()
    except Exception as e:
        print(f"[Erro de verificação] {e}")

# Verificação manual
async def verificar_pagamento(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = query.from_user.id
    await query.answer()

    transaction_id = transaction_tracker.get(user_id)
    if not transaction_id:
        await query.message.reply_text("❌ Nenhuma transação encontrada para verificar.")
        return

    url = PUSHINPAY_CHECK_PIX_URL.replace("{ID}", transaction_id)
    headers = {
        "Authorization": f"Bearer {PUSHINPAY_API_TOKEN}",
        "Accept": "application/json",
        "Content-Type": "application/json"
    }

    try:
        resp = requests.get(url, headers=headers, timeout=20)
        if resp.status_code == 404 or not resp.json():
            await query.message.reply_text("❌ Pagamento ainda não aprovado.")
            return

        data = resp.json()
        status = data.get("status")

        if status == "paid":
            await query.message.reply_text("✅ Pagamento aprovado!")
            await query.message.reply_text(f"🎁 Conteúdo liberado:\n{LINK_PREMIUM}")
        else:
            await query.message.reply_text("⏳ Pagamento ainda não aprovado.")
    except Exception as e:
        await query.message.reply_text(f"Erro ao verificar pagamento: {e}")

# Inicialização do bot
def main():
    app = Application.builder().token(TELEGRAM_BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(gerar_pix, pattern="gerar_pix"))
    app.add_handler(CallbackQueryHandler(verificar_pagamento, pattern="verificar_pagamento"))
    app.run_polling()
    print("🛑 Bot encerrado.")

if __name__ == "__main__":
    main()

