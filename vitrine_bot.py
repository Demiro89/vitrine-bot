"""
Bot Vitrine — YouTubePremiumDisneyBot
Redirige automatiquement vers le bot principal @abonnementpro_bot
"""

import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes

BOT_TOKEN    = "8755971087:AAGfh_4XDGNnU3lFmU3lprwpWReP4uLxQyc"
MAIN_BOT     = "https://t.me/abonnementpro_bot"

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
    handlers=[logging.FileHandler("vitrine.log"), logging.StreamHandler()]
)
logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────
# MESSAGE D'ACCUEIL
# ─────────────────────────────────────────────

WELCOME_MSG = """🎬 *YouTube Premium & Disney+ à prix réduit !*

✅ *Nos offres :*

▶️ *YouTube Premium*
• Sans publicité
• Téléchargements illimités
• YouTube Music inclus
• Dès *5.99 €/mois* _(officiel : 13.99€)_

🏰 *Disney+*
• Marvel, Star Wars, Pixar
• National Geographic
• Contenu exclusif
• Dès *4.99 €/mois* _(officiel : 11.99€)_

💳 *Paiement* : PayPal · USDT · SOL · XRP
🔄 *Résiliation* à tout moment
⚡ *Accès* rapide après paiement

👇 *Cliquez pour vous abonner maintenant :*"""

async def start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    kb = [[InlineKeyboardButton("🚀 S'abonner maintenant", url=MAIN_BOT)]]
    await update.message.reply_text(
        WELCOME_MSG,
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(kb)
    )
    logger.info(f"Nouveau visiteur vitrine: {update.effective_user.id}")

async def any_message(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Répond à n'importe quel message avec l'offre + bouton."""
    kb = [[InlineKeyboardButton("🚀 S'abonner maintenant", url=MAIN_BOT)]]
    await update.message.reply_text(
        WELCOME_MSG,
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(kb)
    )

def main():
    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, any_message))
    logger.info("✅ Bot vitrine YouTubePremiumDisneyBot démarré")
    app.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()
