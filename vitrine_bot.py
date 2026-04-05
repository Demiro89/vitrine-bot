"""
Bot Vitrine — @YouTubePremiumDisneyBot
Redirige vers le bot principal @abonnementpro_bot
"""
import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes

BOT_TOKEN = "8755971087:AAGfh_4XDGNnU3lFmU3lprwpWReP4uLxQyc"
MAIN_BOT  = "https://t.me/abonnementpro_bot"

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
    handlers=[logging.FileHandler("vitrine.log"), logging.StreamHandler()]
)
logger = logging.getLogger(__name__)

WELCOME_MSG = (
    "🎬 *YouTube Premium & Disney+ à prix réduit !*\n\n"
    "━━━━━━━━━━━━━━━━━━\n"
    "▶️ *YouTube Premium* — dès *5.99€/mois*\n"
    "   ~~Prix officiel : 13.99€~~ → *économisez 57%*\n"
    "   ✅ Zéro pub · YouTube Music · Téléchargements\n\n"
    "🏰 *Disney+* — dès *4.99€/mois*\n"
    "   ~~Prix officiel : 15.99€~~ → *économisez 69%*\n"
    "   ✅ 4K HDR · Marvel · Star Wars · Pixar\n"
    "━━━━━━━━━━━━━━━━━━\n\n"
    "💳 *Paiements :* CB · PayPal · Crypto\n"
    "⚡ *Accès instantané* après validation\n"
    "🔄 *Résiliation* à tout moment\n"
    "💬 *Support* 7j/7 via Telegram\n\n"
    "👇 *Cliquez pour accéder aux offres :*"
)

def get_kb():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🚀 Voir les offres & S'abonner", url=MAIN_BOT)],
        [InlineKeyboardButton("▶️ YouTube Premium 5.99€/mois",  url=f"{MAIN_BOT}?start=yt")],
        [InlineKeyboardButton("🏰 Disney+ 4.99€/mois",          url=f"{MAIN_BOT}?start=disney")],
        [InlineKeyboardButton("💬 Support & Questions",          url=f"{MAIN_BOT}?start=support")],
    ])

async def start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(WELCOME_MSG, parse_mode="Markdown", reply_markup=get_kb())
    logger.info(f"Visiteur vitrine: {update.effective_user.id}")

async def any_message(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(WELCOME_MSG, parse_mode="Markdown", reply_markup=get_kb())

def main():
    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, any_message))
    logger.info("✅ Bot vitrine démarré")
    app.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()
