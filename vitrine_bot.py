"""
Bot Telegram — YouTube Premium & Disney+
Paiements : PayPal · USDT · SOL · XRP
"""

import logging
import json
import httpx
from datetime import datetime, timedelta
from telegram import (
    Update, InlineKeyboardButton, InlineKeyboardMarkup
)
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler,
    MessageHandler, filters, ContextTypes
)

import os
import os as _os

if _os.path.exists("config.json"):
    with open("config.json") as f:
        CFG = json.load(f)
else:
    CFG = {}

def _env(key, default=None):
    return _os.environ.get(key) or CFG.get(key, default)

BOT_TOKEN        = _env("BOT_TOKEN")
ADMIN_IDS        = [int(x) for x in str(_env("ADMIN_IDS", "0")).split(",") if x.strip().isdigit()]
PAYPAL_LINK_BASE = _env("PAYPAL_LINK_BASE", "https://paypal.me/AccesPremium89/")
PRIVATE_CHAT_ID  = _env("PRIVATE_CHAT_ID", "")

WALLETS = {
    "sol":       _env("WALLET_SOL",        CFG.get("WALLET_SOL", "")),
    "usdttrc20": _env("WALLET_USDT_TRC20", CFG.get("WALLET_USDT_TRC20", "")),
    "xrp":       _env("WALLET_XRP",        CFG.get("WALLET_XRP", "")),
}

SERVICES = {
    "youtube": {
        "name":        "YouTube Premium",
        "emoji":       "▶️",
        "desc":        "Sans pub, téléchargements, YouTube Music inclus",
        "price_month": 5.99,
        "price_year":  54.99,
        "access_mode": "email_invite",
    },
    "disney": {
        "name":        "Disney+",
        "emoji":       "🏰",
        "desc":        "Marvel, Star Wars, Pixar, National Geographic",
        "price_month": 4.99,
        "price_year":  44.99,
        "access_mode": "credentials",
    },
}

CRYPTO_INFO = {
    "sol":       {"name": "Solana (SOL)",  "emoji": "🌐", "network": "Réseau Solana",       "ticker": "SOL"},
    "usdttrc20": {"name": "USDT (TRC-20)", "emoji": "💵", "network": "Réseau TRON (TRC-20)", "ticker": "USDT"},
    "xrp":       {"name": "XRP (Ripple)",  "emoji": "💧", "network": "Réseau XRP Ledger",    "ticker": "XRP"},
}
COINGECKO_IDS = {"sol": "solana", "usdttrc20": "tether", "xrp": "ripple"}
# Prix de secours mis à jour automatiquement toutes les heures
FALLBACK_PRICES = {"sol": 130.0, "usdttrc20": 0.92, "xrp": 0.50}
_price_cache: dict = {}
CACHE_TTL = 300
DB_FILE   = "subscribers.json"
COMMISSION_RATE = 0.15  # 15% de commission

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
    handlers=[logging.FileHandler("bot.log"), logging.StreamHandler()]
)
logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────
# PRIX CRYPTO
# ─────────────────────────────────────────────

async def get_crypto_price_eur(currency: str):
    cg_id  = COINGECKO_IDS.get(currency)
    if not cg_id:
        return FALLBACK_PRICES.get(currency)
    now    = datetime.now().timestamp()
    cached = _price_cache.get(cg_id)
    if cached and (now - cached[1]) < CACHE_TTL:
        return cached[0]
    try:
        # Essai 1 : endpoint simple
        url = f"https://api.coingecko.com/api/v3/simple/price?ids={cg_id}&vs_currencies=eur"
        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.get(url)
            r.raise_for_status()
            data = r.json()
            if cg_id in data and "eur" in data[cg_id]:
                price = float(data[cg_id]["eur"])
                _price_cache[cg_id] = (price, now)
                logger.info(f"Prix {currency}: {price} EUR")
                return price
            else:
                logger.warning(f"CoinGecko: clé manquante pour {cg_id}, data={data}")
    except Exception as e:
        logger.warning(f"CoinGecko error ({cg_id}): {e}")
    # Fallback : prix de secours
    fallback = FALLBACK_PRICES.get(currency)
    logger.warning(f"Utilisation prix de secours pour {currency}: {fallback} EUR")
    return fallback

async def eur_to_crypto(amount_eur: float, currency: str):
    price = await get_crypto_price_eur(currency)
    if not price or price <= 0:
        logger.error(f"Prix introuvable pour {currency}")
        return "?"
    amount = amount_eur / price
    if currency == "usdttrc20":
        return f"{amount:.2f}"
    elif currency == "xrp":
        return f"{amount:.4f}"
    else:  # sol
        return f"{amount:.5f}"

# ─────────────────────────────────────────────
# BASE DE DONNÉES
# ─────────────────────────────────────────────

def load_db():
    if os.path.exists(DB_FILE):
        with open(DB_FILE) as f:
            return json.load(f)
    return {"subscribers": {}, "crypto_pending": {}, "awaiting_email": {}, "custom_services": {}}

def get_all_services() -> dict:
    """Retourne les services de base + les services ajoutés par l'admin."""
    db       = load_db()
    combined = dict(SERVICES)  # copie des services de base
    combined.update(db.get("custom_services", {}))
    return combined

def save_db(db):
    with open(DB_FILE, "w") as f:
        json.dump(db, f, indent=2, default=str)

def get_user_services(user_id: int) -> dict:
    return load_db()["subscribers"].get(str(user_id), {})

def get_service_sub(user_id: int, service_id: str):
    return get_user_services(user_id).get(service_id)

def set_service_sub(user_id: int, service_id: str, plan: str, days: int):
    db  = load_db()
    uid = str(user_id)
    db["subscribers"].setdefault(uid, {})
    existing = db["subscribers"][uid].get(service_id)
    if existing and existing.get("expires_at") and not existing.get("cancelled"):
        current_exp = datetime.fromisoformat(existing["expires_at"])
        base = current_exp if current_exp > datetime.now() else datetime.now()
    else:
        base = datetime.now()
    new_exp = base + timedelta(days=days)
    db["subscribers"][uid][service_id] = {
        "plan":          plan,
        "started_at":    existing.get("started_at", datetime.now().isoformat()) if existing else datetime.now().isoformat(),
        "expires_at":    new_exp.isoformat(),
        "reminder_sent": False,
        "profile_info":  existing.get("profile_info", "") if existing else "",
        "cancelled":     False,
        "access_sent":   False,
    }
    save_db(db)
    return new_exp

def cancel_service_sub(user_id: int, service_id: str):
    db  = load_db()
    uid = str(user_id)
    if uid in db["subscribers"] and service_id in db["subscribers"][uid]:
        db["subscribers"][uid][service_id]["cancelled"] = True
        save_db(db)
        return True
    return False

def set_profile_info(user_id: int, service_id: str, info: str):
    db  = load_db()
    uid = str(user_id)
    if uid in db["subscribers"] and service_id in db["subscribers"][uid]:
        db["subscribers"][uid][service_id]["profile_info"] = info
        db["subscribers"][uid][service_id]["access_sent"]  = True
        save_db(db)
        return True
    return False

def is_service_active(user_id: int, service_id: str) -> bool:
    sub = get_service_sub(user_id, service_id)
    return bool(sub and not sub.get("cancelled") and
                datetime.fromisoformat(sub["expires_at"]) > datetime.now())

def get_active_subscribers(service_id: str) -> list:
    db  = load_db()
    now = datetime.now()
    result = []
    for uid, subs in db["subscribers"].items():
        sub = subs.get(service_id)
        if isinstance(sub, dict) and not sub.get("cancelled") \
           and sub.get("expires_at") \
           and datetime.fromisoformat(sub["expires_at"]) > now:
            result.append((uid, sub))
    return result

def generate_referral_code(user_id: int) -> str:
    """Génère un code de parrainage unique."""
    import hashlib
    return "REF" + hashlib.md5(str(user_id).encode()).hexdigest()[:6].upper()

def get_or_create_affiliate(user_id: int, username: str = "") -> dict:
    """Récupère ou crée le compte affilié d'un utilisateur."""
    db  = load_db()
    uid = str(user_id)
    affiliates = db.setdefault("affiliates", {})
    if uid not in affiliates:
        affiliates[uid] = {
            "username":      username,
            "code":          generate_referral_code(user_id),
            "referrals":     [],       # liste des user_id parrainés
            "earnings":      0.0,      # total gagné
            "pending":       0.0,      # en attente de paiement
            "paid":          0.0,      # déjà payé
            "created_at":    datetime.now().isoformat()
        }
        save_db(db)
    return affiliates[uid]

def get_affiliate_by_code(code: str):
    """Trouve un affilié par son code de parrainage."""
    db = load_db()
    for uid, aff in db.get("affiliates", {}).items():
        if aff.get("code", "").upper() == code.upper():
            return uid, aff
    return None, None

def add_commission(affiliate_uid: str, amount: float, service: str, referred_uid: int):
    """Ajoute une commission à un affilié."""
    db  = load_db()
    aff = db.get("affiliates", {}).get(affiliate_uid)
    if not aff:
        return
    commission = round(amount * COMMISSION_RATE, 2)
    aff["earnings"] = round(aff.get("earnings", 0) + commission, 2)
    aff["pending"]  = round(aff.get("pending",  0) + commission, 2)
    aff.setdefault("history", []).append({
        "date":         datetime.now().isoformat(),
        "service":      service,
        "amount":       amount,
        "commission":   commission,
        "referred_uid": referred_uid
    })
    if str(referred_uid) not in aff.get("referrals", []):
        aff["referrals"].append(str(referred_uid))
    save_db(db)
    return commission

def save_referral_pending(user_id: int, code: str):
    """Sauvegarde le code de parrainage utilisé lors de l'inscription."""
    db = load_db()
    db.setdefault("referral_pending", {})[str(user_id)] = code
    save_db(db)

def get_referral_code_for_user(user_id: int):
    """Récupère le code de parrainage utilisé par un utilisateur."""
    db = load_db()
    return db.get("referral_pending", {}).get(str(user_id))

def save_crypto_pending(ref: str, user_id: int, service_id: str,
                        plan_key: str, currency: str, amount: str, price_eur: float):
    db = load_db()
    db.setdefault("crypto_pending", {})[ref] = {
        "user_id":    user_id, "service_id": service_id,
        "plan_key":   plan_key, "currency":  currency,
        "amount":     amount,   "price_eur": price_eur,
        "created_at": datetime.now().isoformat()
    }
    save_db(db)

def pop_crypto_pending(ref: str):
    db   = load_db()
    data = db.get("crypto_pending", {}).pop(ref, None)
    save_db(db)
    return data

# ─────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────

def is_admin(user_id: int) -> bool:
    return user_id in ADMIN_IDS

def fmt_date(iso: str) -> str:
    return datetime.fromisoformat(iso).strftime("%d/%m/%Y")

def days_left_count(iso: str) -> int:
    return max(0, (datetime.fromisoformat(iso) - datetime.now()).days)

def make_ref(user_id: int, currency: str) -> str:
    return f"{currency[:3].upper()}{int(datetime.now().timestamp())}{str(user_id)[-4:]}"

def service_summary(user_id: int) -> str:
    subs  = get_user_services(user_id)
    lines = []
    for sid, sub in subs.items():
        svc = SERVICES.get(sid)
        if not svc or sub.get("cancelled"):
            continue
        exp = datetime.fromisoformat(sub["expires_at"])
        if exp > datetime.now():
            remaining   = (exp - datetime.now()).days
            access_icon = "🔑" if sub.get("profile_info") else "⏳"
            lines.append(
                f"{svc['emoji']} *{svc['name']}* — {sub['plan']} {access_icon}\n"
                f"   📅 Expire le {fmt_date(sub['expires_at'])} _(J-{remaining})_"
            )
    return "\n\n".join(lines) if lines else "Aucun abonnement actif."

# ─────────────────────────────────────────────
# ACTIVATION ABONNEMENT
# ─────────────────────────────────────────────

async def activate_subscription(bot, user_id: int, service_id: str,
                                 plan_key: str, method: str = ""):
    svc         = SERVICES[service_id]
    plan        = "Mensuel" if plan_key == "month" else "Annuel"
    days        = 31 if plan_key == "month" else 366
    exp         = set_service_sub(user_id, service_id, plan, days)
    access_mode = svc.get("access_mode", "credentials")
    method_txt  = f" via *{method}*" if method else ""

    if access_mode == "email_invite":
        msg = (
            f"🎉 *Paiement validé{method_txt} !*\n\n"
            f"▶️ *YouTube Premium* — Plan *{plan}*\n"
            f"📅 Valide jusqu'au : *{fmt_date(exp.isoformat())}*\n\n"
            "📧 *Pour activer votre accès, j'ai besoin de votre adresse Gmail.*\n\n"
            "⚠️ _Il doit s'agir du Gmail associé à votre compte YouTube._\n\n"
            "👇 *Envoyez votre adresse Gmail maintenant :*"
        )
        await bot.send_message(user_id, msg, parse_mode="Markdown")
        db = load_db()
        db.setdefault("awaiting_email", {})[str(user_id)] = {
            "service_id": service_id, "plan_key": plan_key, "expires_at": exp.isoformat()
        }
        save_db(db)
    else:
        msg = (
            f"🎉 *Paiement reçu{method_txt} !*\n\n"
            f"🏰 *Disney+* — Plan *{plan}*\n"
            f"📅 Valide jusqu'au : *{fmt_date(exp.isoformat())}*\n\n"
            "⏳ *Votre paiement est en cours de vérification.*\n\n"
            "Dès validation, vous recevrez vos identifiants ici. 🔑\n"
            "📋 Retrouvez-les via /menu → Mes abonnements"
        )
        await bot.send_message(user_id, msg, parse_mode="Markdown")

    for aid in ADMIN_IDS:
        if access_mode == "email_invite":
            await bot.send_message(
                aid,
                f"🔔 *Nouvel abonnement YouTube*\n\n"
                f"👤 User : `{user_id}`\n"
                f"📦 Plan : *{plan}* ({method})\n"
                f"📅 Expire : {fmt_date(exp.isoformat())}\n\n"
                "📧 _En attente de l'email Gmail du client._",
                parse_mode="Markdown"
            )
        else:
            kb = [[
                InlineKeyboardButton("✅ Valider & envoyer accès", callback_data=f"admin_send_access_{user_id}_disney"),
                InlineKeyboardButton("❌ Rejeter",                  callback_data=f"admin_reject_{user_id}"),
            ]]
            await bot.send_message(
                aid,
                f"🔔 *Nouveau paiement Disney+ à valider*\n\n"
                f"👤 User : `{user_id}`\n"
                f"📦 Plan : *{plan}* ({method})\n"
                f"📅 Expire : {fmt_date(exp.isoformat())}\n\n"
                "👉 Vérifiez le paiement puis validez :",
                parse_mode="Markdown",
                reply_markup=InlineKeyboardMarkup(kb)
            )
    # ── Calculer et attribuer la commission si parrainage ──
    ref_code = get_referral_code_for_user(user_id)
    if ref_code:
        aff_uid, aff = get_affiliate_by_code(ref_code)
        if aff_uid and aff_uid != str(user_id):
            price_paid = svc["price_month"] if plan_key == "month" else svc["price_year"]
            commission = add_commission(aff_uid, price_paid, svc["name"], user_id)
            if commission:
                try:
                    nom_svc = svc['name']
                    await bot.send_message(
                        int(aff_uid),
                        f"🎉 *Nouvelle commission gagnée !*\n\n"
                        f"Un client parrainé vient de s'abonner à *{nom_svc}*\n"
                        f"💰 Commission : *+{commission} €* (15%)\n\n"
                        "Consultez votre tableau de bord : /affiliation",
                        parse_mode="Markdown"
                    )
                except Exception:
                    pass

    logger.info(f"Activé: user={user_id}, service={service_id}, plan={plan}, méthode={method}")
    return exp

# ─────────────────────────────────────────────
# /start
# ─────────────────────────────────────────────

async def start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    # Détecter le code de parrainage dans le lien /start ref_XXXXXX
    args = ctx.args
    if args and args[0].startswith("ref_"):
        code = args[0][4:].upper()
        aff_uid, aff = get_affiliate_by_code(code)
        if aff_uid and aff_uid != str(user.id):
            save_referral_pending(user.id, code)
            await update.message.reply_text(
                "🎁 *Vous avez été parrainé !*\n\n"
                "Vous bénéficiez d'un accès à nos services premium.\n\n"
                "Découvrez nos offres 👇",
                parse_mode="Markdown"
            )
    kb   = [
        [InlineKeyboardButton("📺 Voir les services",    callback_data="catalog")],
        [InlineKeyboardButton("📋 Mes abonnements",      callback_data="my_subs")],
        [InlineKeyboardButton("ℹ️ Comment ça marche ?",  callback_data="howto")],
        [InlineKeyboardButton("💬 Contacter le support", callback_data="support_menu")],
        [InlineKeyboardButton("🤝 Programme d'affiliation", callback_data="affiliation")],
    ]
    if is_admin(user.id):
        kb.append([InlineKeyboardButton("⚙️ Panel Admin", callback_data="admin")])
    await update.message.reply_text(
        f"👋 Bienvenue *{user.first_name}* !\n\n"
        "🎯 Accédez à vos plateformes préférées à prix réduit :\n\n"
        "▶️ *YouTube Premium* · 🏰 *Disney+*\n\n"
        "🅿️ PayPal · 💵 USDT · 🌐 SOL · 💧 XRP\n"
        "🔄 Résiliation à tout moment\n\n"
        "Choisissez une option 👇",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(kb)
    )

# ─────────────────────────────────────────────
# /menu
# ─────────────────────────────────────────────

async def menu(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    kb   = [
        [InlineKeyboardButton("📺 Voir les services",    callback_data="catalog")],
        [InlineKeyboardButton("📋 Mes abonnements",      callback_data="my_subs")],
        [InlineKeyboardButton("💬 Contacter le support", callback_data="support_menu")],
        [InlineKeyboardButton("❌ Résilier",             callback_data="cancel_menu")],
    ]
    if is_admin(user.id):
        kb.append([InlineKeyboardButton("⚙️ Panel Admin", callback_data="admin")])
    await update.message.reply_text(
        "📱 *Menu principal*\n\nQue souhaitez-vous faire ?",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(kb)
    )

# ─────────────────────────────────────────────
# CALLBACKS
# ─────────────────────────────────────────────

async def button_handler(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query    = update.callback_query
    await query.answer()
    data     = query.data
    user     = query.from_user
    ALL_SVCS = get_all_services()  # services de base + services ajoutés par admin

    # ── Catalogue ────────────────────────────
    if data == "catalog":
        kb = []
        for sid, svc in ALL_SVCS.items():
            kb.append([InlineKeyboardButton(
                f"{svc['emoji']} {svc['name']} — dès {svc['price_month']} €/mois",
                callback_data=f"service_{sid}"
            )])
        kb.append([InlineKeyboardButton("◀️ Retour", callback_data="back_start")])
        await query.edit_message_text(
            "📺 *Nos services :*\n\nCliquez pour voir les détails 👇",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(kb)
        )

    # ── Détail service ────────────────────────
    elif data.startswith("service_"):
        sid = data[8:]
        svc = ALL_SVCS.get(sid)
        if not svc:
            return
        savings    = round((1 - svc["price_year"] / (svc["price_month"] * 12)) * 100)
        is_sub     = is_service_active(user.id, sid)
        sub_info   = get_service_sub(user.id, sid)
        status_txt = ""
        if is_sub and sub_info:
            status_txt = f"\n✅ *Abonné* — expire le {fmt_date(sub_info['expires_at'])}\n"
        kb = []
        if not is_sub:
            kb.append([
                InlineKeyboardButton(f"📅 Mensuel — {svc['price_month']} €", callback_data=f"plan_{sid}_month"),
                InlineKeyboardButton(f"🗓 Annuel — {svc['price_year']} €",   callback_data=f"plan_{sid}_year"),
            ])
        else:
            kb.append([InlineKeyboardButton("🔄 Renouveler", callback_data=f"plan_{sid}_month")])
        kb.append([InlineKeyboardButton("◀️ Retour", callback_data="catalog")])
        await query.edit_message_text(
            f"{svc['emoji']} *{svc['name']}*\n\n"
            f"📝 {svc['desc']}\n{status_txt}\n"
            f"💰 *Tarifs :*\n"
            f"• Mensuel : *{svc['price_month']} €/mois*\n"
            f"• Annuel : *{svc['price_year']} €/an* _(−{savings}%)_\n\n"
            "⚡ Accès envoyé après validation du paiement\n"
            "🔄 Résiliation possible à tout moment",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(kb)
        )

    # ── Choix plan ────────────────────────────
    elif data.startswith("plan_"):
        parts    = data.split("_")
        sid      = parts[1]
        plan_key = parts[2]
        svc      = ALL_SVCS.get(sid)
        if not svc:
            return
        price = svc["price_month"] if plan_key == "month" else svc["price_year"]
        plan  = "Mensuel" if plan_key == "month" else "Annuel"
        ctx.user_data.update(pending_service=sid, pending_plan=plan,
                             pending_price=price, pending_plan_key=plan_key)
        savings     = round((1 - svc["price_year"] / (svc["price_month"] * 12)) * 100)
        annual_hint = f"\n💡 _Annuel = −{savings}% d'économie !_" if plan_key == "month" else ""
        kb = [
            [InlineKeyboardButton("🅿️ PayPal",          callback_data=f"pay_paypal_{sid}_{plan_key}")],
            [InlineKeyboardButton("💵 USDT (TRC-20)",    callback_data=f"pay_crypto_usdttrc20_{sid}_{plan_key}")],
            [InlineKeyboardButton("🌐 Solana (SOL)",     callback_data=f"pay_crypto_sol_{sid}_{plan_key}")],
            [InlineKeyboardButton("💧 XRP (Ripple)",     callback_data=f"pay_crypto_xrp_{sid}_{plan_key}")],
            [InlineKeyboardButton("◀️ Retour",           callback_data=f"service_{sid}")],
        ]
        await query.edit_message_text(
            f"{svc['emoji']} *{svc['name']}* — *{plan}*\n"
            f"💰 Prix : *{price} €*{annual_hint}\n\n"
            "Choisissez votre méthode de paiement :",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(kb)
        )

    # ── PayPal ────────────────────────────────
    elif data.startswith("pay_paypal_"):
        parts    = data[len("pay_paypal_"):].split("_")
        sid      = parts[0]
        plan_key = parts[1]
        svc      = SERVICES.get(sid, {})
        price    = ctx.user_data.get("pending_price", svc.get("price_month", 9.99))
        plan     = ctx.user_data.get("pending_plan", "Mensuel")
        paypal_url = f"{PAYPAL_LINK_BASE}{price}EUR"
        kb = [
            [InlineKeyboardButton("🅿️ Payer sur PayPal",     url=paypal_url)],
            [InlineKeyboardButton("✅ J'ai payé — Confirmer", callback_data=f"confirm_paypal_{sid}_{plan_key}")],
        ]
        await query.edit_message_text(
            f"🅿️ *PayPal — {svc.get('name',sid)} {plan} ({price} €)*\n\n"
            "1️⃣ Cliquez *Payer sur PayPal*\n"
            "2️⃣ Effectuez le paiement\n"
            "3️⃣ Revenez ici et cliquez *J'ai payé*",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(kb)
        )

    # ── PayPal confirmation ───────────────────
    elif data.startswith("confirm_paypal_"):
        parts    = data[len("confirm_paypal_"):].split("_")
        sid      = parts[0]
        plan_key = parts[1]
        svc      = SERVICES.get(sid, {})
        price    = ctx.user_data.get("pending_price", svc.get("price_month", 9.99))
        plan     = "Mensuel" if plan_key == "month" else "Annuel"
        for aid in ADMIN_IDS:
            kb_admin = [[
                InlineKeyboardButton("✅ Valider",  callback_data=f"admin_approve_paypal_{user.id}_{sid}_{plan_key}"),
                InlineKeyboardButton("❌ Rejeter",  callback_data=f"admin_reject_{user.id}"),
            ]]
            await ctx.bot.send_message(
                aid,
                f"🔔 *Validation PayPal*\n\n"
                f"👤 [{user.full_name}](tg://user?id={user.id}) (`{user.id}`)\n"
                f"{svc.get('emoji','')} *{svc.get('name',sid)}* — *{plan}* — *{price} €*\n\n"
                f"🔗 Vérifiez sur [PayPal.me](https://paypal.me/AccesPremium89) puis validez :",
                parse_mode="Markdown",
                reply_markup=InlineKeyboardMarkup(kb_admin)
            )
        await query.edit_message_text(
            "⏳ *Demande envoyée à l'admin.* Vous serez notifié dès validation.",
            parse_mode="Markdown"
        )

    # ── CRYPTO ────────────────────────────────
    elif data.startswith("pay_crypto_"):
        rest = data[len("pay_crypto_"):]
        for cur in ("usdttrc20", "sol", "xrp"):
            if rest.startswith(cur + "_"):
                currency = cur
                rest2    = rest[len(cur) + 1:]
                break
        else:
            return
        parts    = rest2.split("_")
        sid      = parts[0]
        plan_key = parts[1]
        svc      = SERVICES.get(sid, {})
        price    = ctx.user_data.get("pending_price", svc.get("price_month", 9.99))
        plan     = "Mensuel" if plan_key == "month" else "Annuel"
        info     = CRYPTO_INFO[currency]
        await query.edit_message_text(
            f"{info['emoji']} *Récupération du cours {info['ticker']}…*",
            parse_mode="Markdown"
        )
        amount_crypto = await eur_to_crypto(price, currency)
        if amount_crypto == "?":
            kb = [[InlineKeyboardButton("◀️ Choisir une autre méthode", callback_data=f"plan_{sid}_{plan_key}")]]
            await query.edit_message_text(
                f"❌ *Impossible de récupérer le cours {info['ticker']} en ce moment.*\n\n"
                "Réessayez dans quelques minutes ou choisissez une autre méthode de paiement.",
                parse_mode="Markdown",
                reply_markup=InlineKeyboardMarkup(kb)
            )
            return
        ref    = make_ref(user.id, currency)
        wallet = WALLETS[currency]
        save_crypto_pending(ref, user.id, sid, plan_key, currency, amount_crypto, price)
        kb = [
            [InlineKeyboardButton("✅ J'ai payé — Confirmer", callback_data=f"confirm_crypto_{ref}_{sid}_{plan_key}")],
            [InlineKeyboardButton("◀️ Changer de méthode",    callback_data=f"plan_{sid}_{plan_key}")],
        ]
        await query.edit_message_text(
            f"{info['emoji']} *Paiement {info['name']}*\n\n"
            f"{svc.get('emoji','')} *{svc.get('name',sid)}* — *{plan}*\n"
            f"🔗 Réseau : *{info['network']}*\n\n"
            f"💰 Montant à envoyer :\n`{amount_crypto} {info['ticker']}`\n"
            f"_(≈ {price} €)_\n\n"
            f"📬 Adresse :\n`{wallet}`\n\n"
            f"🔖 Référence : `{ref}`\n\n"
            "⚠️ *Envoyez exactement ce montant.*\n"
            "✅ Cliquez *J'ai payé* après l'envoi.",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(kb)
        )

    # ── Crypto confirmation ───────────────────
    elif data.startswith("confirm_crypto_"):
        rest     = data[len("confirm_crypto_"):]
        idx1     = rest.index("_")
        ref      = rest[:idx1]
        rest2    = rest[idx1 + 1:]
        parts    = rest2.split("_")
        sid      = parts[0]
        plan_key = parts[1]
        db       = load_db()
        pending  = db.get("crypto_pending", {}).get(ref)
        if not pending:
            await query.answer("⚠️ Référence introuvable.", show_alert=True)
            return
        svc  = SERVICES.get(sid, {})
        info = CRYPTO_INFO.get(pending["currency"], {"name": pending["currency"], "emoji": "🪙", "ticker": ""})
        plan = "Mensuel" if plan_key == "month" else "Annuel"
        for aid in ADMIN_IDS:
            kb_admin = [[
                InlineKeyboardButton("✅ Valider",  callback_data=f"admin_approve_crypto_{user.id}_{ref}_{sid}_{plan_key}"),
                InlineKeyboardButton("❌ Rejeter",  callback_data=f"admin_reject_crypto_{user.id}_{ref}"),
            ]]
            explorer = {
                "sol":       f"https://explorer.solana.com/address/{WALLETS['sol']}",
                "usdttrc20": f"https://tronscan.org/#/address/{WALLETS['usdttrc20']}",
                "xrp":       f"https://xrpscan.com/account/{WALLETS['xrp']}",
            }.get(pending["currency"], "")
            if explorer:
                kb_admin.append([InlineKeyboardButton("🔍 Vérifier sur explorateur", url=explorer)])
            await ctx.bot.send_message(
                aid,
                f"🔔 *Paiement crypto à valider*\n\n"
                f"👤 [{user.full_name}](tg://user?id={user.id}) (`{user.id}`)\n"
                f"{svc.get('emoji','')} *{svc.get('name',sid)}* — *{plan}* — *{pending['price_eur']} €*\n"
                f"{info['emoji']} `{pending['amount']} {info['ticker']}`\n"
                f"🔖 Réf : `{ref}`",
                parse_mode="Markdown",
                reply_markup=InlineKeyboardMarkup(kb_admin)
            )
        await query.edit_message_text(
            f"⏳ *Confirmation envoyée !*\n\n🔖 Réf : `{ref}`\n\n"
            "L'admin va vérifier et activer votre accès. ✅",
            parse_mode="Markdown"
        )

    # ── Admin : Valider PayPal ────────────────
    elif data.startswith("admin_approve_paypal_"):
        if not is_admin(user.id):
            await query.answer("⛔ Accès refusé.", show_alert=True)
            return
        parts    = data[len("admin_approve_paypal_"):].split("_")
        target   = int(parts[0])
        sid      = parts[1]
        plan_key = parts[2]
        await activate_subscription(ctx.bot, target, sid, plan_key, "PayPal")
        await query.edit_message_text(
            f"✅ PayPal validé — {SERVICES.get(sid,{}).get('name',sid)} pour `{target}`",
            parse_mode="Markdown"
        )

    # ── Admin : Valider Crypto ────────────────
    elif data.startswith("admin_approve_crypto_"):
        if not is_admin(user.id):
            await query.answer("⛔ Accès refusé.", show_alert=True)
            return
        rest     = data[len("admin_approve_crypto_"):]
        parts    = rest.split("_")
        target   = int(parts[0])
        ref      = parts[1]
        sid      = parts[2]
        plan_key = parts[3]
        pop_crypto_pending(ref)
        await activate_subscription(ctx.bot, target, sid, plan_key, "Crypto")
        await query.edit_message_text(
            f"✅ Crypto validé — {SERVICES.get(sid,{}).get('name',sid)} pour `{target}`",
            parse_mode="Markdown"
        )

    # ── Admin : Rejeter ───────────────────────
    elif data.startswith("admin_reject_crypto_"):
        if not is_admin(user.id):
            await query.answer("⛔ Accès refusé.", show_alert=True)
            return
        parts  = data.split("_")
        target = int(parts[3])
        ref    = parts[4] if len(parts) > 4 else ""
        pop_crypto_pending(ref)
        await ctx.bot.send_message(target, "❌ *Paiement crypto non validé.*", parse_mode="Markdown")
        await query.edit_message_text(f"❌ Rejeté pour `{target}`.", parse_mode="Markdown")

    elif data.startswith("admin_pay_affiliate_"):
        if not is_admin(user.id):
            await query.answer("⛔ Accès refusé.", show_alert=True)
            return
        parts   = data[len("admin_pay_affiliate_"):].split("_")
        target  = int(parts[0])
        amount  = float(parts[1])
        db      = load_db()
        uid_str = str(target)
        if uid_str in db.get("affiliates", {}):
            db["affiliates"][uid_str]["pending"] = max(0, round(db["affiliates"][uid_str].get("pending", 0) - amount, 2))
            db["affiliates"][uid_str]["paid"]    = round(db["affiliates"][uid_str].get("paid", 0) + amount, 2)
            save_db(db)
        await ctx.bot.send_message(
            target,
            f"✅ *Paiement de commission reçu !*\n\n💰 Montant : *{amount} €*\n\nMerci pour votre participation au programme d'affiliation ! 🎉",
            parse_mode="Markdown"
        )
        await query.edit_message_text(f"✅ Paiement de *{amount} €* confirmé pour `{target}`.", parse_mode="Markdown")

    elif data.startswith("admin_reject_affiliate_"):
        if not is_admin(user.id):
            await query.answer("⛔ Accès refusé.", show_alert=True)
            return
        target = int(data.split("_")[3])
        await ctx.bot.send_message(
            target,
            "❌ *Votre demande de paiement a été refusée.*\n\nContactez le support pour plus d'informations.",
            parse_mode="Markdown"
        )
        await query.edit_message_text(f"❌ Demande de paiement refusée pour `{target}`.", parse_mode="Markdown")

    elif data.startswith("admin_reject_"):
        if not is_admin(user.id):
            await query.answer("⛔ Accès refusé.", show_alert=True)
            return
        target = int(data.split("_")[2])
        await ctx.bot.send_message(target, "❌ *Paiement non validé.*\nContactez le support.", parse_mode="Markdown")
        await query.edit_message_text(f"❌ Rejeté pour `{target}`.", parse_mode="Markdown")

    # ── Admin : Envoyer accès ─────────────────
    elif data.startswith("admin_send_access_"):
        if not is_admin(user.id):
            await query.answer("⛔ Accès refusé.", show_alert=True)
            return
        parts    = data[len("admin_send_access_"):].split("_")
        target   = parts[0]
        sid      = parts[1]
        svc      = ALL_SVCS.get(sid, {})
        sub      = get_service_sub(int(target), sid)
        existing = sub.get("profile_info", "") if sub else ""
        hint     = f"\n📋 Accès actuels : `{existing}`\n" if existing else ""
        ctx.user_data["edit_target_uid"] = target
        ctx.user_data["edit_target_sid"] = sid
        kb = [
            [InlineKeyboardButton("🔑 Identifiants + mot de passe", callback_data=f"access_type_creds_{target}_{sid}")],
            [InlineKeyboardButton("🔗 Lien d'invitation",           callback_data=f"access_type_link_{target}_{sid}")],
            [InlineKeyboardButton("📦 Les deux",                     callback_data=f"access_type_both_{target}_{sid}")],
            [InlineKeyboardButton("◀️ Retour",                       callback_data=f"admin_edit_{sid}_list")],
        ]
        nom = svc.get("name", sid)
        emo = svc.get("emoji", "")
        await query.edit_message_text(
            f"📤 *Envoyer les accès {emo} {nom} à `{target}`*\n{hint}\n"
            "Quel type d'accès voulez-vous envoyer ?",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(kb)
        )

    elif data.startswith("access_type_"):
        if not is_admin(user.id):
            return
        # format: access_type_<type>_<target>_<sid>
        rest      = data[len("access_type_"):]
        # type peut être creds, link, ou both
        for t in ("creds", "link", "both"):
            if rest.startswith(t + "_"):
                access_type = t
                rest2       = rest[len(t) + 1:]
                break
        else:
            return
        parts  = rest2.split("_")
        target = parts[0]
        sid    = parts[1]
        svc    = ALL_SVCS.get(sid, {})
        ctx.user_data["awaiting_edit_access"]  = True
        ctx.user_data["edit_target_uid"]       = target
        ctx.user_data["edit_target_sid"]       = sid
        ctx.user_data["edit_access_type"]      = access_type
        nom = svc.get("name", sid)
        emo = svc.get("emoji", "")
        if access_type == "creds":
            prompt = (
                f"🔑 *Identifiants {emo} {nom} pour `{target}`*\n\n"
                "Tapez les identifiants :\n"
                "_(Ex: email@example.com / MotDePasse123)_"
            )
        elif access_type == "link":
            prompt = (
                f"🔗 *Lien d'invitation {emo} {nom} pour `{target}`*\n\n"
                "Tapez le lien d'invitation :\n"
                "_(Ex: https://invite.example.com/XXXX)_"
            )
        else:
            prompt = (
                f"📦 *Identifiants + Lien {emo} {nom} pour `{target}`*\n\n"
                "Tapez les identifiants ET le lien sur des lignes séparées :\n\n"
                "_(Ex:\nemail@example.com / MotDePasse123\nhttps://invite.example.com/XXXX)_"
            )
        await query.edit_message_text(prompt, parse_mode="Markdown")

    # ── Admin : YouTube invitation confirmée ──
    elif data.startswith("yt_invite_sent_"):
        if not is_admin(user.id):
            await query.answer("⛔ Accès refusé.", show_alert=True)
            return
        target = int(data[len("yt_invite_sent_"):])
        set_profile_info(target, "youtube", "Invitation YouTube Premium envoyée ✅")
        await ctx.bot.send_message(
            target,
            "✅ *Votre invitation YouTube Premium a été envoyée !*\n\n"
            "📩 Vérifiez votre boîte Gmail et acceptez l'invitation.\n"
            "💡 _Si vous ne trouvez pas l'email, vérifiez vos spams._",
            parse_mode="Markdown"
        )
        await query.edit_message_text(f"✅ Invitation YouTube confirmée pour `{target}`.", parse_mode="Markdown")

    # ── Mes abonnements ───────────────────────
    elif data == "my_subs":
        summary = service_summary(user.id)
        subs    = get_user_services(user.id)
        kb      = []
        for sid, sub in subs.items():
            svc = SERVICES.get(sid)
            if svc and not sub.get("cancelled") and datetime.fromisoformat(sub["expires_at"]) > datetime.now():
                label = "🔑 Voir mes accès" if sub.get("profile_info") else "⏳ Accès en attente"
                kb.append([
                    InlineKeyboardButton(f"{svc['emoji']} {label}", callback_data=f"show_access_{sid}"),
                    InlineKeyboardButton("❌ Résilier",              callback_data=f"cancel_confirm_{sid}"),
                ])
        kb.append([InlineKeyboardButton("📺 Ajouter un service", callback_data="catalog")])
        kb.append([InlineKeyboardButton("◀️ Retour",             callback_data="back_start")])
        await query.edit_message_text(
            f"📋 *Mes abonnements*\n\n{summary}",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(kb)
        )

    # ── Voir accès ────────────────────────────
    elif data.startswith("show_access_"):
        sid = data[len("show_access_"):]
        sub = get_service_sub(user.id, sid)
        svc = SERVICES.get(sid, {})
        if not sub:
            await query.answer("Abonnement introuvable.", show_alert=True)
            return
        if sub.get("cancelled") or datetime.fromisoformat(sub["expires_at"]) <= datetime.now():
            kb = [[InlineKeyboardButton("🔄 Se réabonner", callback_data=f"service_{sid}")]]
            await query.edit_message_text(
                f"❌ *Abonnement {svc.get('name',sid)} expiré ou résilié.*\n\n"
                "Les identifiants sont réservés aux abonnés actifs.",
                parse_mode="Markdown",
                reply_markup=InlineKeyboardMarkup(kb)
            )
            return
        profile    = sub.get("profile_info", "")
        access_txt = f"\n\n🔑 *Vos accès :*\n`{profile}`" if profile \
                     else "\n\n⏳ _Vos identifiants sont en cours d'envoi par l'admin._"
        kb = [[InlineKeyboardButton("◀️ Retour", callback_data="my_subs")]]
        await query.edit_message_text(
            f"{svc.get('emoji','')} *{svc.get('name',sid)}*\n"
            f"📦 Plan : *{sub['plan']}*\n"
            f"📅 Expire le : *{fmt_date(sub['expires_at'])}* _(J-{days_left_count(sub['expires_at'])})_"
            f"{access_txt}\n\n"
            "⚠️ _Ne partagez jamais vos accès._\n"
            "🔒 _Accessibles uniquement aux abonnés actifs._",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(kb)
        )

    # ── Résiliation ───────────────────────────
    elif data == "cancel_menu":
        subs   = get_user_services(user.id)
        actifs = [(sid, sub) for sid, sub in subs.items()
                  if not sub.get("cancelled") and datetime.fromisoformat(sub["expires_at"]) > datetime.now()]
        if not actifs:
            await query.edit_message_text(
                "ℹ️ Aucun abonnement actif à résilier.",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("◀️ Retour", callback_data="back_start")]])
            )
            return
        kb = []
        for sid, sub in actifs:
            svc = SERVICES.get(sid, {})
            kb.append([InlineKeyboardButton(
                f"❌ {svc.get('emoji','')} {svc.get('name',sid)} (expire {fmt_date(sub['expires_at'])})",
                callback_data=f"cancel_confirm_{sid}"
            )])
        kb.append([InlineKeyboardButton("◀️ Retour", callback_data="back_start")])
        await query.edit_message_text(
            "❌ *Résilier un abonnement*\n\nChoisissez le service :",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(kb)
        )

    elif data.startswith("cancel_confirm_"):
        sid = data[len("cancel_confirm_"):]
        svc = SERVICES.get(sid, {})
        sub = get_service_sub(user.id, sid)
        if not sub:
            await query.answer("Abonnement introuvable.", show_alert=True)
            return
        kb = [[
            InlineKeyboardButton("✅ Confirmer",  callback_data=f"cancel_do_{sid}"),
            InlineKeyboardButton("◀️ Annuler",   callback_data="my_subs"),
        ]]
        await query.edit_message_text(
            f"⚠️ *Confirmer la résiliation ?*\n\n"
            f"{svc.get('emoji','')} *{svc.get('name',sid)}*\n"
            f"📅 Actif jusqu'au *{fmt_date(sub['expires_at'])}*\n\n"
            "Vous gardez l'accès jusqu'à cette date.",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(kb)
        )

    elif data.startswith("cancel_do_"):
        sid = data[len("cancel_do_"):]
        svc = SERVICES.get(sid, {})
        sub = get_service_sub(user.id, sid)
        ok  = cancel_service_sub(user.id, sid)
        if ok:
            exp = sub["expires_at"] if sub else ""
            for aid in ADMIN_IDS:
                await ctx.bot.send_message(
                    aid,
                    f"🔔 *Résiliation utilisateur*\n\n"
                    f"👤 `{user.id}` ({user.full_name})\n"
                    f"{svc.get('emoji','')} *{svc.get('name',sid)}*\n"
                    f"📅 Accès jusqu'au : {fmt_date(exp) if exp else 'N/A'}",
                    parse_mode="Markdown"
                )
            kb = [[InlineKeyboardButton("📺 Voir les services", callback_data="catalog")]]
            await query.edit_message_text(
                f"✅ *{svc.get('name',sid)} résilié.*\n\n"
                f"Accès conservé jusqu'au *{fmt_date(exp)}*.",
                parse_mode="Markdown",
                reply_markup=InlineKeyboardMarkup(kb)
            )

    # ── Comment ça marche ─────────────────────
    elif data == "howto":
        kb = [[InlineKeyboardButton("📺 Voir les services", callback_data="catalog")]]
        await query.edit_message_text(
            "ℹ️ *Comment ça marche ?*\n\n"
            "1️⃣ Choisissez un service et un plan\n"
            "2️⃣ Payez par PayPal ou crypto\n"
            "3️⃣ Recevez vos accès après validation\n"
            "4️⃣ Profitez !\n\n"
            "▶️ *YouTube* : envoyez votre Gmail → invitation sous peu\n"
            "🏰 *Disney+* : identifiants envoyés après validation paiement\n\n"
            "🔄 Résiliation à tout moment\n"
            "❓ Problème ? /support",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(kb)
        )

    # ── PANEL ADMIN ───────────────────────────
    elif data == "admin":
        if not is_admin(user.id):
            await query.answer("⛔ Accès refusé.", show_alert=True)
            return
        db  = load_db()
        now = datetime.now()
        total_users  = len(db["subscribers"])
        total_active = 0
        expiring_3d  = 0
        for subs in db["subscribers"].values():
            for sub in subs.values():
                if isinstance(sub, dict) and not sub.get("cancelled") \
                   and sub.get("expires_at") \
                   and datetime.fromisoformat(sub["expires_at"]) > now:
                    total_active += 1
                    if (datetime.fromisoformat(sub["expires_at"]) - now).days <= 3:
                        expiring_3d += 1
        pending_crypto = len(db.get("crypto_pending", {}))
        pending_email  = len(db.get("awaiting_email", {}))
        lines = []
        for sid, svc in SERVICES.items():
            actifs     = get_active_subscribers(sid)
            sans_acces = sum(1 for _, s in actifs if not s.get("profile_info"))
            lines.append(
                f"{svc['emoji']} *{svc['name']}* : *{len(actifs)}* actifs"
                + (f" _(⏳ {sans_acces} sans accès)_" if sans_acces else "")
            )
        alert = ""
        if expiring_3d:
            alert += f"\n⚠️ *{expiring_3d} abonnement(s) expirent dans 3 jours !*"
        if pending_email:
            alert += f"\n📧 *{pending_email} email(s) YouTube en attente*"
        kb = [
            [InlineKeyboardButton("📋 Liste abonnés",             callback_data="admin_list")],
            [InlineKeyboardButton("🏰 Gérer accès Disney+",       callback_data="admin_edit_disney_list")],
            [InlineKeyboardButton("▶️ Gérer accès YouTube",       callback_data="admin_edit_youtube_list")],
            [InlineKeyboardButton("🏰 Màj mot de passe Disney+",  callback_data="admin_update_disney")],
            [InlineKeyboardButton("🪙 Crypto en attente",          callback_data="admin_crypto_pending")],
            [InlineKeyboardButton("📢 Broadcast",                  callback_data="admin_broadcast")],
            [InlineKeyboardButton("➕ Ajouter un service",         callback_data="admin_add_service")],
            [InlineKeyboardButton("🗑 Supprimer un service",       callback_data="admin_del_service")],
            [InlineKeyboardButton("🤝 Voir les affiliés",            callback_data="admin_affiliates")],
            [InlineKeyboardButton("🔗 Générer un lien affilié",      callback_data="admin_genlink")],
            [InlineKeyboardButton("🚫 Résilier un abonné",            callback_data="admin_cancel_menu")],
        ]
        await query.edit_message_text(
            f"⚙️ *Panel Admin*\n\n"
            f"👥 Utilisateurs : *{total_users}* | ✅ Actifs : *{total_active}*\n"
            f"🪙 Crypto en attente : *{pending_crypto}*"
            f"{alert}\n\n"
            "*Par service :*\n" + "\n".join(lines),
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(kb)
        )

    elif data == "admin_genlink":
        if not is_admin(user.id):
            return
        ctx.user_data["awaiting_genlink_name"] = True
        await query.edit_message_text(
            "🔗 *Générer un lien de parrainage*\n\n"
            "Tapez le nom ou @username de la personne :\n"
            "_(Ex: Jean ou @jean_dupont)_\n\n"
            "💡 Si la personne n'existe pas encore dans le système, "
            "un nouveau compte affilié sera créé automatiquement.",
            parse_mode="Markdown"
        )

    elif data == "admin_affiliates":
        if not is_admin(user.id):
            return
        db         = load_db()
        affiliates = db.get("affiliates", {})
        if not affiliates:
            kb = [[InlineKeyboardButton("◀️ Retour", callback_data="admin")]]
            await query.edit_message_text(
                "ℹ️ Aucun affilié enregistré pour le moment.\n\n"
                "Les affiliés apparaissent ici dès qu'un utilisateur clique sur "
                "🤝 Programme d'affiliation.",
                reply_markup=InlineKeyboardMarkup(kb)
            )
            return
        lines = []
        total_pending = 0.0
        for uid, aff in sorted(affiliates.items(),
                               key=lambda x: x[1].get("earnings", 0), reverse=True):
            name      = aff.get("username") or f"User {uid}"
            code      = aff.get("code", "?")
            referrals = len(aff.get("referrals", []))
            earnings  = aff.get("earnings", 0.0)
            pending   = aff.get("pending",  0.0)
            paid      = aff.get("paid",     0.0)
            total_pending += pending
            status = "💰" if pending > 0 else "✅" if paid > 0 else "👤"
            lines.append(
                f"{status} *{name}* — Code: `{code}`\n"
                f"   👥 {referrals} client(s) · 💰 {earnings}€ gagné · ⏳ {pending}€ en attente"
            )
        kb = [
            [InlineKeyboardButton("◀️ Retour", callback_data="admin")]
        ]
        # Telegram limite les messages à 4096 caractères — on pagine si nécessaire
        header = f"🤝 *Affiliés ({len(affiliates)}) — Total en attente : {round(total_pending,2)} €*\n\n"
        body   = "\n\n".join(lines)
        msg    = header + body
        if len(msg) > 4000:
            # Envoyer en plusieurs messages
            await query.edit_message_text(
                header + "\n\n".join(lines[:20]),
                parse_mode="Markdown",
                reply_markup=InlineKeyboardMarkup(kb)
            )
            for chunk_start in range(20, len(lines), 20):
                chunk = "\n\n".join(lines[chunk_start:chunk_start+20])
                await ctx.bot.send_message(query.from_user.id, chunk, parse_mode="Markdown")
        else:
            await query.edit_message_text(
                msg,
                parse_mode="Markdown",
                reply_markup=InlineKeyboardMarkup(kb)
            )

    elif data == "admin_list":
        if not is_admin(user.id):
            return
        db    = load_db()
        now   = datetime.now()
        lines = []
        for uid, subs in list(db["subscribers"].items())[:20]:
            for sid, sub in subs.items():
                if not isinstance(sub, dict):
                    continue
                svc = SERVICES.get(sid, {})
                if not sub.get("cancelled") and sub.get("expires_at") \
                   and datetime.fromisoformat(sub["expires_at"]) > now:
                    d   = (datetime.fromisoformat(sub["expires_at"]) - now).days
                    acc = "🔑" if sub.get("profile_info") else "⏳"
                    lines.append(f"✅{acc} `{uid}` {svc.get('emoji','')} J-{d}")
                else:
                    lines.append(f"❌ `{uid}` {svc.get('emoji','')} expiré")
        kb = [[InlineKeyboardButton("◀️ Retour", callback_data="admin")]]
        await query.edit_message_text(
            "📋 *Abonnés (20 derniers) :*\n\n"
            "✅🔑 actif+accès · ✅⏳ actif sans accès · ❌ expiré\n\n"
            + ("\n".join(lines) or "Aucun abonné"),
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(kb)
        )

    elif data in ("admin_edit_disney_list", "admin_edit_youtube_list"):
        if not is_admin(user.id):
            return
        sid    = "disney" if "disney" in data else "youtube"
        svc    = SERVICES.get(sid, {})
        actifs = get_active_subscribers(sid)
        if not actifs:
            kb = [[InlineKeyboardButton("◀️ Retour", callback_data="admin")]]
            await query.edit_message_text(
                f"ℹ️ Aucun abonné actif pour *{svc.get('name',sid)}*.",
                parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(kb)
            )
            return
        kb = []
        for uid, sub in actifs[:20]:
            days_n = (datetime.fromisoformat(sub["expires_at"]) - datetime.now()).days
            icon   = "🔑" if sub.get("profile_info") else "⏳"
            kb.append([InlineKeyboardButton(
                f"{icon} `{uid}` — J-{days_n} ({fmt_date(sub['expires_at'])})",
                callback_data=f"admin_send_access_{uid}_{sid}"
            )])
        kb.append([InlineKeyboardButton("◀️ Retour", callback_data="admin")])
        nom = svc.get('name', sid)
        emo = svc.get('emoji', '')
        await query.edit_message_text(
            f"✏️ *Abonnés actifs {emo} {nom}*\n\n"
            "🔑 accès envoyés · ⏳ pas encore envoyés\n\n"
            "Cliquez pour envoyer/modifier les identifiants :",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(kb)
        )

    elif data == "admin_update_disney":
        if not is_admin(user.id):
            return
        ctx.user_data["awaiting_disney_update"] = True
        actifs = get_active_subscribers("disney")
        await query.edit_message_text(
            f"🏰 *Màj identifiants Disney+*\n\n"
            f"👥 *{len(actifs)}* abonné(s) actif(s) seront notifiés.\n\n"
            "Tapez les nouveaux identifiants dans le chat :\n"
            "_(Ex: email@disney.com / NouveauMotDePasse)_",
            parse_mode="Markdown"
        )

    elif data == "admin_crypto_pending":
        if not is_admin(user.id):
            return
        db      = load_db()
        pending = db.get("crypto_pending", {})
        if not pending:
            kb = [[InlineKeyboardButton("◀️ Retour", callback_data="admin")]]
            await query.edit_message_text("✅ Aucun paiement crypto en attente.",
                                          reply_markup=InlineKeyboardMarkup(kb))
            return
        lines = []
        for ref, p in list(pending.items())[:15]:
            svc  = SERVICES.get(p.get("service_id", ""), {})
            info = CRYPTO_INFO.get(p.get("currency", ""), {"emoji": "🪙", "ticker": ""})
            lines.append(
                f"{info['emoji']} `{ref}` | `{p['user_id']}` | "
                f"{svc.get('name','?')[:8]} | {p.get('amount','?')} {info['ticker']} | {p.get('price_eur','?')}€"
            )
        kb = [[InlineKeyboardButton("◀️ Retour", callback_data="admin")]]
        await query.edit_message_text(
            "🪙 *Crypto en attente :*\n\n" + "\n".join(lines),
            parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(kb)
        )

    elif data == "admin_broadcast":
        if not is_admin(user.id):
            return
        ctx.user_data["awaiting_broadcast"] = True
        total = sum(len(get_active_subscribers(sid)) for sid in SERVICES)
        await query.edit_message_text(
            f"📢 *Broadcast*\n\n👥 *{total}* abonné(s) actif(s) recevront le message.\n\nÉcrivez votre message :",
            parse_mode="Markdown"
        )

    elif data == "admin_add_service":
        if not is_admin(user.id):
            return
        ctx.user_data["awaiting_add_service"] = True
        await query.edit_message_text(
            "➕ *Ajouter un nouveau service*\n\n"
            "Tapez les informations dans ce format exact :\n\n"
            "`id|Nom du service|emoji|description|prix_mensuel|prix_annuel|mode`\n\n"
            "*Exemples :*\n"
            "`netflix|Netflix|🎬|Films et séries HD|6.99|64.99|credentials`\n"
            "`spotify|Spotify Premium|🎵|Musique sans pub|4.99|44.99|credentials`\n"
            "`duolingo|Duolingo Super|🦉|Apprentissage des langues|3.99|34.99|credentials`\n\n"
            "*Modes disponibles :*\n"
            "• `credentials` = vous envoyez les identifiants\n"
            "• `email_invite` = invitation par email (comme YouTube)",
            parse_mode="Markdown"
        )

    elif data == "admin_del_service":
        if not is_admin(user.id):
            return
        db          = load_db()
        custom_svcs = db.get("custom_services", {})
        if not custom_svcs:
            kb = [[InlineKeyboardButton("◀️ Retour", callback_data="admin")]]
            await query.edit_message_text(
                "ℹ️ Aucun service personnalisé à supprimer.\n\n"
                "_Les services YouTube et Disney+ sont fixes et ne peuvent pas être supprimés._",
                reply_markup=InlineKeyboardMarkup(kb)
            )
            return
        kb = []
        for sid, svc in custom_svcs.items():
            kb.append([InlineKeyboardButton(
                f"🗑 {svc.get('emoji','')} {svc.get('name',sid)}",
                callback_data=f"admin_del_confirm_{sid}"
            )])
        kb.append([InlineKeyboardButton("◀️ Retour", callback_data="admin")])
        await query.edit_message_text(
            "🗑 *Supprimer un service*\n\nChoisissez le service à supprimer :",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(kb)
        )

    elif data.startswith("admin_del_confirm_"):
        if not is_admin(user.id):
            return
        sid = data[len("admin_del_confirm_"):]
        db  = load_db()
        svc = db.get("custom_services", {}).get(sid, {})
        kb  = [[
            InlineKeyboardButton("✅ Confirmer suppression", callback_data=f"admin_del_do_{sid}"),
            InlineKeyboardButton("◀️ Annuler",               callback_data="admin_del_service"),
        ]]
        nom_svc = svc.get('name', sid)
        emo_svc = svc.get('emoji', '')
        await query.edit_message_text(
            f"⚠️ *Confirmer la suppression de {emo_svc} {nom_svc} ?*\n\n"
            "_Ce service ne sera plus visible par les clients._",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(kb)
        )

    elif data.startswith("admin_del_do_"):
        if not is_admin(user.id):
            return
        sid = data[len("admin_del_do_"):]
        db  = load_db()
        svc = db.get("custom_services", {}).pop(sid, {})
        save_db(db)
        kb  = [[InlineKeyboardButton("⚙️ Panel Admin", callback_data="admin")]]
        await query.edit_message_text(
            f"✅ Service *{svc.get('name',sid)}* supprimé.",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(kb)
        )

    elif data == "admin_cancel_menu":
        if not is_admin(user.id):
            return
        all_svcs = get_all_services()
        ctx.user_data["awaiting_admin_cancel"] = True
        await query.edit_message_text(
            "🚫 *Résilier un abonnement*\n\nTapez : `<user_id> <service>`\nEx: `123456789 disney`\n\nServices : " + " · ".join(all_svcs.keys()),
            parse_mode="Markdown"
        )

    elif data == "support_menu":
        ctx.user_data["awaiting_support_msg"] = True
        kb = [[InlineKeyboardButton("◀️ Annuler", callback_data="back_start")]]
        await query.edit_message_text(
            "💬 *Contacter le support*\n\n"
            "Décrivez votre problème ou votre question.\n"
            "L'admin vous répondra dès que possible. ⏱\n\n"
            "_(Tapez votre message maintenant)_",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(kb)
        )

    elif data.startswith("admin_reply_"):
        if not is_admin(user.id):
            await query.answer("⛔ Accès refusé.", show_alert=True)
            return
        target = int(data[len("admin_reply_"):])
        ctx.user_data["awaiting_reply_to"] = target
        await query.edit_message_text(
            f"💬 *Répondre à l'utilisateur* `{target}`\n\n"
            "Tapez votre réponse dans le chat :",
            parse_mode="Markdown"
        )

    elif data == "affiliation":
        aff = get_or_create_affiliate(user.id, user.username or user.first_name)
        code      = aff["code"]
        earnings  = aff.get("earnings", 0.0)
        pending   = aff.get("pending",  0.0)
        paid      = aff.get("paid",     0.0)
        referrals = len(aff.get("referrals", []))
        history   = aff.get("history", [])[-5:]  # 5 dernières commissions
        link      = f"https://t.me/abonnementpro_bot?start=ref_{code}"
        hist_txt  = ""
        if history:
            hist_txt = "\n\n📊 *Dernières commissions :*\n"
            for h in reversed(history):
                date = h["date"][:10]
                hist_txt += f"• {date} — {h['service']} — +{h['commission']} €\n"
        kb = [
            [InlineKeyboardButton("💸 Demander un paiement", callback_data="aff_request_payment")],
            [InlineKeyboardButton("📤 Partager mon lien",    callback_data="aff_share_link")],
            [InlineKeyboardButton("◀️ Retour",               callback_data="back_start")],
        ]
        await query.edit_message_text(
            f"🤝 *Programme d'affiliation*\n\n"
            f"🔗 Votre lien de parrainage :\n`{link}`\n\n"
            f"📊 *Statistiques :*\n"
            f"👥 Clients parrainés : *{referrals}*\n"
            f"💰 Total gagné : *{earnings} €*\n"
            f"⏳ En attente : *{pending} €*\n"
            f"✅ Déjà payé : *{paid} €*"
            f"{hist_txt}\n"
            "💡 _Gagnez 15% sur chaque abonnement de vos filleuls !_",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(kb)
        )

    elif data == "aff_share_link":
        aff  = get_or_create_affiliate(user.id, user.username or user.first_name)
        code = aff["code"]
        link = f"https://t.me/abonnementpro_bot?start=ref_{code}"
        await query.edit_message_text(
            f"📤 *Partagez ce lien pour gagner des commissions !*\n\n"
            f"`{link}`\n\n"
            "💡 *Message à copier-coller :*\n\n"
            f"_🎬 YouTube Premium dès 5.99€/mois et Disney+ dès 4.99€/mois !\n"
            f"Paiement PayPal ou crypto, accès rapide ✅\n"
            f"👉 {link}_\n\n"
            "📊 Vous gagnez *15%* sur chaque abonnement payé par vos filleuls !",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("◀️ Retour", callback_data="affiliation")]])
        )

    elif data == "aff_request_payment":
        aff     = get_or_create_affiliate(user.id, user.username or user.first_name)
        pending = aff.get("pending", 0.0)
        if pending < 5.0:
            await query.edit_message_text(
                f"⚠️ *Solde insuffisant*\n\n"
                f"Votre solde en attente est de *{pending} €*.\n"
                "Le minimum de retrait est de *5 €*.\n\n"
                "Continuez à parrainer pour atteindre le seuil !",
                parse_mode="Markdown",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("◀️ Retour", callback_data="affiliation")]])
            )
            return
        ctx.user_data["awaiting_payment_info"] = True
        ctx.user_data["payment_amount"]        = pending
        await query.edit_message_text(
            f"💸 *Demande de paiement — {pending} €*\n\n"
            "Envoyez-moi votre adresse PayPal ou wallet crypto pour recevoir votre paiement :\n\n"
            "_(Ex: email@paypal.com ou adresse USDT TRC-20)_",
            parse_mode="Markdown"
        )

    elif data == "back_start":
        kb = [
            [InlineKeyboardButton("📺 Voir les services",   callback_data="catalog")],
            [InlineKeyboardButton("📋 Mes abonnements",     callback_data="my_subs")],
            [InlineKeyboardButton("ℹ️ Comment ça marche ?", callback_data="howto")],
        ]
        if is_admin(user.id):
            kb.append([InlineKeyboardButton("⚙️ Panel Admin", callback_data="admin")])
        await query.edit_message_text(
            f"👋 Bienvenue *{user.first_name}* !\n\n"
            "🎯 Accédez à vos plateformes préférées à prix réduit :\n\n"
            "▶️ *YouTube Premium* · 🏰 *Disney+*\n\n"
            "🅿️ PayPal · 💵 USDT · 🌐 SOL · 💧 XRP\n"
            "🔄 Résiliation à tout moment\n\n"
            "Choisissez une option 👇",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(kb)
        )

# ─────────────────────────────────────────────
# MESSAGES TEXTE
# ─────────────────────────────────────────────

async def text_handler(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    text = update.message.text.strip()

    # ── YouTube : réception email Gmail ──────
    db_tmp = load_db()
    if str(user.id) in db_tmp.get("awaiting_email", {}):
        email_text = text.strip().lower()
        if "@" in email_text and "." in email_text:
            db_tmp["awaiting_email"].pop(str(user.id))
            save_db(db_tmp)
            set_profile_info(user.id, "youtube", f"Gmail: {email_text}")
            await update.message.reply_text(
                f"✅ *Adresse Gmail reçue !*\n\n📧 `{email_text}`\n\n"
                "L'admin va envoyer l'invitation YouTube sur cet email.\n"
                "📩 _Vérifiez votre boîte mail dans les prochaines minutes._",
                parse_mode="Markdown"
            )
            for aid in ADMIN_IDS:
                kb_yt = [[InlineKeyboardButton("✅ Invitation envoyée", callback_data=f"yt_invite_sent_{user.id}")]]
                await ctx.bot.send_message(
                    aid,
                    f"📧 *Email YouTube reçu !*\n\n"
                    f"👤 `{user.id}` ({user.full_name})\n"
                    f"📧 Gmail : `{email_text}`\n\n"
                    "👉 *À faire :*\n"
                    "1. Ouvrez YouTube Premium Famille\n"
                    "2. Invitez ce Gmail\n"
                    "3. Cliquez *Invitation envoyée* :",
                    parse_mode="Markdown",
                    reply_markup=InlineKeyboardMarkup(kb_yt)
                )
        else:
            await update.message.reply_text(
                "❌ *Email invalide.*\nEntrez votre adresse Gmail complète :\n_(Ex: prenom@gmail.com)_",
                parse_mode="Markdown"
            )
        return

    # ── Admin : envoyer accès individuel ─────
    if ctx.user_data.get("awaiting_edit_access") and is_admin(user.id):
        ctx.user_data["awaiting_edit_access"] = False
        target_str  = ctx.user_data.pop("edit_target_uid", None)
        sid         = ctx.user_data.pop("edit_target_sid", None)
        access_type = ctx.user_data.pop("edit_access_type", "creds")
        if not target_str or not sid:
            await update.message.reply_text("❌ Session expirée. Recommencez.")
            return
        target   = int(target_str)
        all_svcs = get_all_services()
        svc      = all_svcs.get(sid, {})
        nom      = svc.get("name", sid)
        emo      = svc.get("emoji", "")
        info     = text.strip()
        set_profile_info(target, sid, info)
        sub = get_service_sub(target, sid)
        is_active_sub = sub and not sub.get("cancelled") and \
                        datetime.fromisoformat(sub["expires_at"]) > datetime.now()
        if is_active_sub:
            # Construire le message client selon le type d'accès
            if access_type == "creds":
                client_msg = (
                    f"🔑 *Vos identifiants {nom} sont prêts !*\n\n"
                    f"`{info}`\n\n"
                    "📋 Retrouvez-les via /menu → Mes abonnements → Voir accès\n"
                    "⚠️ _Ne partagez jamais ces informations._"
                )
            elif access_type == "link":
                client_msg = (
                    f"🔗 *Votre lien d'invitation {emo} {nom} est prêt !*\n\n"
                    f"{info}\n\n"
                    "👆 Cliquez le lien pour rejoindre.\n"
                    "📋 Retrouvez-le via /menu → Mes abonnements → Voir accès"
                )
            else:  # both
                client_msg = (
                    f"📦 *Vos accès {emo} {nom} sont prêts !*\n\n"
                    f"{info}\n\n"
                    "📋 Retrouvez-les via /menu → Mes abonnements → Voir accès\n"
                    "⚠️ _Ne partagez jamais vos identifiants._"
                )
            await ctx.bot.send_message(target, client_msg, parse_mode="Markdown")
        # Retour admin
        sid_key = sid if sid in ("disney", "youtube") else sid
        kb = [
            [InlineKeyboardButton("◀️ Retour liste", callback_data=f"admin_edit_{sid_key}_list")],
            [InlineKeyboardButton("⚙️ Panel Admin",  callback_data="admin")],
        ]
        await update.message.reply_text(
            f"✅ Accès *{nom}* envoyés à `{target}` !"
            + ("\n📩 Client notifié." if is_active_sub else "\n⚠️ Abonnement inactif."),
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(kb)
        )
        return

    # ── Admin : Màj Disney+ tous abonnés ─────
    if ctx.user_data.get("awaiting_disney_update") and is_admin(user.id):
        ctx.user_data["awaiting_disney_update"] = False
        db   = load_db()
        sent = failed = 0
        for uid, subs in db["subscribers"].items():
            sub = subs.get("disney")
            if isinstance(sub, dict) and not sub.get("cancelled") \
               and sub.get("expires_at") \
               and datetime.fromisoformat(sub["expires_at"]) > datetime.now():
                db["subscribers"][uid]["disney"]["profile_info"] = text.strip()
                db["subscribers"][uid]["disney"]["access_sent"]  = True
                try:
                    await ctx.bot.send_message(
                        int(uid),
                        "🏰 *Mise à jour Disney+*\n\n"
                        "Une mise à jour du mot de passe vient d'être effectuée.\n"
                        "Merci de prendre en compte la mise à jour.\n\n"
                        "🔑 Voir vos nouveaux identifiants :\n"
                        "/menu → Mes abonnements → 🏰 Voir mes accès",
                        parse_mode="Markdown"
                    )
                    sent += 1
                except Exception:
                    failed += 1
        save_db(db)
        kb = [[InlineKeyboardButton("⚙️ Panel Admin", callback_data="admin")]]
        await update.message.reply_text(
            f"✅ *Identifiants Disney+ mis à jour !*\n\n"
            f"📩 Notification envoyée à *{sent}* abonné(s). ❌ {failed} échec(s).",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(kb)
        )
        return

    # ── Admin : Résiliation forcée ────────────
    if ctx.user_data.get("awaiting_admin_cancel") and is_admin(user.id):
        ctx.user_data["awaiting_admin_cancel"] = False
        try:
            parts  = text.split()
            target = int(parts[0])
            sid    = parts[1].lower()
            if sid not in SERVICES:
                await update.message.reply_text(f"❌ Service inconnu. Valides: {', '.join(SERVICES.keys())}")
                return
            ok  = cancel_service_sub(target, sid)
            svc = SERVICES.get(sid, {})
            sub = get_service_sub(target, sid)
            if ok:
                await ctx.bot.send_message(
                    target,
                    f"🔔 *Votre abonnement {svc.get('name',sid)} a été résilié.*\n\n"
                    f"📅 Accès jusqu'au *{fmt_date(sub['expires_at']) if sub else 'N/A'}*.",
                    parse_mode="Markdown"
                )
                await update.message.reply_text(f"✅ {svc.get('name',sid)} résilié pour `{target}`.", parse_mode="Markdown")
            else:
                await update.message.reply_text("❌ Abonnement introuvable.")
        except Exception as e:
            await update.message.reply_text(f"Usage : `<user_id> <service>`\nErreur: {e}", parse_mode="Markdown")
        return

    # ── Admin : ajouter un service ───────────────────────────────────────────
    if ctx.user_data.get("awaiting_add_service") and is_admin(user.id):
        ctx.user_data["awaiting_add_service"] = False
        try:
            parts = text.strip().split("|")
            if len(parts) < 7:
                await update.message.reply_text(
                    "❌ Format incorrect. Exemple :\n"
                    "`netflix|Netflix|🎬|Films et séries HD|6.99|64.99|credentials`",
                    parse_mode="Markdown"
                )
                return
            sid         = parts[0].strip().lower().replace(" ", "_")
            nom         = parts[1].strip()
            emoji       = parts[2].strip()
            desc        = parts[3].strip()
            price_month = float(parts[4].strip())
            price_year  = float(parts[5].strip())
            mode        = parts[6].strip()
            if mode not in ("credentials", "email_invite"):
                mode = "credentials"
            # Vérifier que l'ID n'existe pas déjà
            all_svcs = get_all_services()
            if sid in all_svcs:
                await update.message.reply_text(
                    f"❌ L'ID `{sid}` existe déjà. Choisissez un autre identifiant.",
                    parse_mode="Markdown"
                )
                return
            # Sauvegarder dans la DB
            db = load_db()
            db.setdefault("custom_services", {})[sid] = {
                "name":        nom,
                "emoji":       emoji,
                "desc":        desc,
                "price_month": price_month,
                "price_year":  price_year,
                "access_mode": mode,
            }
            save_db(db)
            savings = round((1 - price_year / (price_month * 12)) * 100)
            kb = [[InlineKeyboardButton("⚙️ Panel Admin", callback_data="admin")]]
            await update.message.reply_text(
                f"✅ *Service ajouté avec succès !*\n\n"
                f"{emoji} *{nom}*\n"
                f"📝 {desc}\n"
                f"💰 Mensuel : *{price_month} €* | Annuel : *{price_year} €* (−{savings}%)\n"
                f"🔧 Mode : `{mode}`\n\n"
                f"_Les clients peuvent maintenant voir et acheter ce service._",
                parse_mode="Markdown",
                reply_markup=InlineKeyboardMarkup(kb)
            )
        except Exception as e:
            await update.message.reply_text(
                f"❌ Erreur : {e}\n\nFormat attendu :\n"
                "`id|Nom|emoji|description|prix_mensuel|prix_annuel|mode`",
                parse_mode="Markdown"
            )
        return

    # ── Affilié : demande de paiement ───────────────────────────────────────
    if ctx.user_data.get("awaiting_payment_info"):
        ctx.user_data["awaiting_payment_info"] = False
        amount  = ctx.user_data.pop("payment_amount", 0.0)
        address = text.strip()
        # Notifier l'admin
        for aid in ADMIN_IDS:
            kb_pay = [[
                InlineKeyboardButton("✅ Paiement effectué", callback_data=f"admin_pay_affiliate_{user.id}_{amount}"),
                InlineKeyboardButton("❌ Refuser",           callback_data=f"admin_reject_affiliate_{user.id}"),
            ]]
            await ctx.bot.send_message(
                aid,
                f"💸 *Demande de paiement affilié*\n\n"
                f"👤 [{user.full_name}](tg://user?id={user.id}) (`{user.id}`)\n"
                f"💰 Montant : *{amount} €*\n"
                f"📬 Adresse : `{address}`\n\n"
                "Effectuez le paiement puis confirmez :",
                parse_mode="Markdown",
                reply_markup=InlineKeyboardMarkup(kb_pay)
            )
        await update.message.reply_text(
            f"✅ *Demande envoyée !*\n\n"
            f"💰 Montant : *{amount} €*\n"
            f"📬 Adresse : `{address}`\n\n"
            "L'admin va traiter votre demande sous peu.",
            parse_mode="Markdown"
        )
        return

    # ── Admin : générer lien affilié depuis le Panel ────────────────────────
    if ctx.user_data.get("awaiting_genlink_name") and is_admin(user.id):
        ctx.user_data["awaiting_genlink_name"] = False
        name    = text.strip()
        db      = load_db()
        # Chercher si cet affilié existe déjà par username
        found_uid = None
        found_aff = None
        for uid, aff in db.get("affiliates", {}).items():
            if aff.get("username", "").lower() == name.lstrip("@").lower():
                found_uid = uid
                found_aff = aff
                break
        if found_aff:
            code = found_aff["code"]
            link = f"https://t.me/abonnementpro_bot?start=ref_{code}"
            kb   = [[InlineKeyboardButton("⚙️ Panel Admin", callback_data="admin")]]
            await update.message.reply_text(
                f"🔗 *Lien existant pour {name}*\n\n"
                f"`{link}`\n\n"
                f"📊 {len(found_aff.get('referrals',[]))} client(s) · {found_aff.get('earnings',0)}€ gagné",
                parse_mode="Markdown",
                reply_markup=InlineKeyboardMarkup(kb)
            )
        else:
            import hashlib
            fake_id  = str(abs(hash(name + str(datetime.now().timestamp()))) % 999999999)
            new_code = "REF" + hashlib.md5((name + fake_id).encode()).hexdigest()[:6].upper()
            db.setdefault("affiliates", {})[fake_id] = {
                "username":   name.lstrip("@"),
                "code":       new_code,
                "referrals":  [],
                "earnings":   0.0,
                "pending":    0.0,
                "paid":       0.0,
                "created_at": datetime.now().isoformat()
            }
            save_db(db)
            link = f"https://t.me/abonnementpro_bot?start=ref_{new_code}"
            kb   = [[InlineKeyboardButton("⚙️ Panel Admin", callback_data="admin")]]
            await update.message.reply_text(
                f"✅ *Lien créé pour {name}*\n\n"
                f"🔗 Lien à envoyer :\n`{link}`\n\n"
                f"🏷 Code : `{new_code}`\n\n"
                "Envoyez ce lien à la personne. La commission de 15% lui sera "
                "attribuée automatiquement sur chaque abonnement ! 💰",
                parse_mode="Markdown",
                reply_markup=InlineKeyboardMarkup(kb)
            )
        return

    # ── Broadcast ────────────────────────────
    if ctx.user_data.get("awaiting_broadcast") and is_admin(user.id):
        ctx.user_data["awaiting_broadcast"] = False
        db       = load_db()
        sent     = failed = 0
        notified = set()
        for uid, subs in db["subscribers"].items():
            for sub in subs.values():
                if isinstance(sub, dict) and not sub.get("cancelled") \
                   and sub.get("expires_at") \
                   and datetime.fromisoformat(sub["expires_at"]) > datetime.now() \
                   and uid not in notified:
                    try:
                        await ctx.bot.send_message(int(uid), f"📢 *Message admin :*\n\n{text}", parse_mode="Markdown")
                        sent += 1
                        notified.add(uid)
                    except Exception:
                        failed += 1
        kb = [[InlineKeyboardButton("⚙️ Panel Admin", callback_data="admin")]]
        await update.message.reply_text(
            f"✅ Broadcast envoyé à *{sent}* utilisateurs. ({failed} échecs)",
            parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(kb)
        )
        return

    # ── Client : message de support ─────────────────────────────────────────
    if ctx.user_data.get("awaiting_support_msg"):
        ctx.user_data["awaiting_support_msg"] = False
        # Transmettre le message à l'admin avec bouton Répondre
        for aid in ADMIN_IDS:
            kb_reply = [[InlineKeyboardButton(
                f"💬 Répondre à {user.first_name}",
                callback_data=f"admin_reply_{user.id}"
            )]]
            await ctx.bot.send_message(
                aid,
                f"💬 *Message de support*\n\n"
                f"👤 [{user.full_name}](tg://user?id={user.id}) (`{user.id}`)\n\n"
                f"📩 *Message :*\n{text}",
                parse_mode="Markdown",
                reply_markup=InlineKeyboardMarkup(kb_reply)
            )
        await update.message.reply_text(
            "✅ *Message envoyé au support !*\n\n"
            "L'admin vous répondra dès que possible. ⏱\n\n"
            "_Vous recevrez la réponse directement ici._",
            parse_mode="Markdown"
        )
        return

    # ── Admin : réponse à un client ──────────────────────────────────────────
    if ctx.user_data.get("awaiting_reply_to") and is_admin(user.id):
        target = ctx.user_data.pop("awaiting_reply_to")
        try:
            await ctx.bot.send_message(
                target,
                f"💬 *Réponse du support :*\n\n{text}",
                parse_mode="Markdown"
            )
            await update.message.reply_text(
                f"✅ Réponse envoyée à `{target}`.",
                parse_mode="Markdown"
            )
        except Exception as e:
            await update.message.reply_text(f"❌ Erreur d'envoi : {e}")
        return

    await update.message.reply_text("Utilisez /start ou /menu pour naviguer. 🙂")

# ─────────────────────────────────────────────
# /support
# ─────────────────────────────────────────────

async def cmd_affiliates(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Admin : liste de tous les affiliés avec leurs stats."""
    if not is_admin(update.effective_user.id):
        return
    db         = load_db()
    affiliates = db.get("affiliates", {})
    if not affiliates:
        await update.message.reply_text("Aucun affilié enregistré.")
        return
    lines         = []
    total_pending = 0.0
    for uid, aff in sorted(affiliates.items(),
                           key=lambda x: x[1].get("earnings", 0), reverse=True):
        name      = aff.get("username") or f"User {uid}"
        code      = aff.get("code", "?")
        referrals = len(aff.get("referrals", []))
        earnings  = aff.get("earnings", 0.0)
        pending   = aff.get("pending",  0.0)
        paid      = aff.get("paid",     0.0)
        total_pending += pending
        history   = aff.get("history", [])
        # Détail des clients parrainés
        clients = ""
        if history:
            for h in history[-3:]:
                clients += f"\n     • {h['date'][:10]} {h['service']} +{h['commission']}€"
        lines.append(
            f"👤 *{name}* (`{uid}`)\n"
            f"   Code: `{code}`\n"
            f"   👥 {referrals} client(s) parrainé(s)\n"
            f"   💰 Total: {earnings}€ · ⏳ Dû: {pending}€ · ✅ Payé: {paid}€"
            f"{clients}"
        )
    await update.message.reply_text(
        f"🤝 *Liste des affiliés ({len(affiliates)})*\n"
        f"💸 *Total à payer : {round(total_pending, 2)} €*\n\n"
        + "\n\n".join(lines),
        parse_mode="Markdown"
    )

async def cmd_genlink(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Admin : génère un lien de parrainage pour n'importe qui.
    Usage : /genlink <@username_ou_nom>
    Ou sans argument : génère un lien pour l'utilisateur qui envoie la commande.
    """
    user = update.effective_user
    args = ctx.args

    if is_admin(user.id) and args:
        # Admin génère un lien pour quelqu'un d'autre
        # On cherche d'abord si cet affilié existe déjà
        name = " ".join(args)
        db   = load_db()
        # Chercher par username
        found_uid  = None
        found_aff  = None
        for uid, aff in db.get("affiliates", {}).items():
            if aff.get("username", "").lower() == name.lstrip("@").lower():
                found_uid = uid
                found_aff = aff
                break
        if found_aff:
            code = found_aff["code"]
            link = f"https://t.me/abonnementpro_bot?start=ref_{code}"
            await update.message.reply_text(
                f"🔗 *Lien de parrainage pour @{found_aff.get('username', name)}*\n\n"
                f"`{link}`\n\n"
                f"📊 Stats : {len(found_aff.get('referrals',[]))} client(s) · {found_aff.get('earnings',0)}€ gagné",
                parse_mode="Markdown"
            )
        else:
            # Créer un nouveau compte affilié avec ce nom
            import hashlib
            fake_id  = abs(hash(name)) % 999999999
            new_code = "REF" + hashlib.md5(name.encode()).hexdigest()[:6].upper()
            db.setdefault("affiliates", {})[str(fake_id)] = {
                "username":   name.lstrip("@"),
                "code":       new_code,
                "referrals":  [],
                "earnings":   0.0,
                "pending":    0.0,
                "paid":       0.0,
                "created_at": datetime.now().isoformat()
            }
            save_db(db)
            link = f"https://t.me/abonnementpro_bot?start=ref_{new_code}"
            await update.message.reply_text(
                f"✅ *Lien créé pour {name}*\n\n"
                f"🔗 Lien :\n`{link}`\n\n"
                f"🏷 Code : `{new_code}`\n\n"
                "Envoyez ce lien à la personne. "
                "Dès qu'un client s'abonne via ce lien, la commission lui sera attribuée automatiquement ! 💰",
                parse_mode="Markdown"
            )
    else:
        # L'utilisateur génère son propre lien
        aff  = get_or_create_affiliate(user.id, user.username or user.first_name)
        code = aff["code"]
        link = f"https://t.me/abonnementpro_bot?start=ref_{code}"
        await update.message.reply_text(
            f"🔗 *Votre lien de parrainage*\n\n"
            f"`{link}`\n\n"
            "Partagez ce lien et gagnez *15%* sur chaque abonnement ! 💰\n\n"
            "📊 Vos stats : /affiliation",
            parse_mode="Markdown"
        )

async def cmd_affiliation(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Affiche le tableau de bord affilié."""
    user = update.effective_user
    aff  = get_or_create_affiliate(user.id, user.username or user.first_name)
    code      = aff["code"]
    earnings  = aff.get("earnings", 0.0)
    pending   = aff.get("pending",  0.0)
    paid      = aff.get("paid",     0.0)
    referrals = len(aff.get("referrals", []))
    link      = f"https://t.me/abonnementpro_bot?start=ref_{code}"
    kb = [
        [InlineKeyboardButton("💸 Demander un paiement", callback_data="aff_request_payment")],
        [InlineKeyboardButton("📤 Partager mon lien",    callback_data="aff_share_link")],
    ]
    await update.message.reply_text(
        f"🤝 *Programme d'affiliation*\n\n"
        f"🔗 Votre lien :\n`{link}`\n\n"
        f"👥 Clients parrainés : *{referrals}*\n"
        f"💰 Total gagné : *{earnings} €*\n"
        f"⏳ En attente : *{pending} €*\n"
        f"✅ Déjà payé : *{paid} €*\n\n"
        "💡 _Gagnez 15% sur chaque abonnement de vos filleuls !_",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(kb)
    )

async def support(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    ctx.user_data["awaiting_support_msg"] = True
    await update.message.reply_text(
        "💬 *Contacter le support*\n\n"
        "Décrivez votre problème ou votre question.\n"
        "L'admin vous répondra dès que possible. ⏱\n\n"
        "_(Tapez votre message maintenant)_",
        parse_mode="Markdown"
    )

async def cmd_msg(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Admin : envoyer un message directement à un client."""
    if not is_admin(update.effective_user.id):
        return
    try:
        target  = int(ctx.args[0])
        message = " ".join(ctx.args[1:])
        if not message:
            await update.message.reply_text("Usage : /msg <user_id> <message>")
            return
        await ctx.bot.send_message(
            target,
            f"💬 *Message du support :*\n\n{message}",
            parse_mode="Markdown"
        )
        await update.message.reply_text(
            f"✅ Message envoyé à `{target}`.", parse_mode="Markdown"
        )
    except Exception as e:
        await update.message.reply_text(f"Usage : /msg <user_id> <message>\nErreur: {e}")

# ─────────────────────────────────────────────
# TÂCHES PLANIFIÉES
# ─────────────────────────────────────────────

async def update_fallback_prices(ctx: ContextTypes.DEFAULT_TYPE):
    """Met à jour les prix de secours toutes les heures depuis CoinGecko."""
    global FALLBACK_PRICES
    now = datetime.now().timestamp()
    for currency, cg_id in COINGECKO_IDS.items():
        try:
            url = f"https://api.coingecko.com/api/v3/simple/price?ids={cg_id}&vs_currencies=eur"
            async with httpx.AsyncClient(timeout=10) as client:
                r = await client.get(url)
                r.raise_for_status()
                data = r.json()
                if cg_id in data and "eur" in data[cg_id]:
                    price = float(data[cg_id]["eur"])
                    FALLBACK_PRICES[currency] = price
                    _price_cache[cg_id] = (price, now)
                    logger.info(f"Prix mis à jour — {currency}: {price} EUR")
        except Exception as e:
            logger.warning(f"Mise à jour prix échouée pour {currency}: {e}")

async def check_expirations(ctx: ContextTypes.DEFAULT_TYPE):
    db  = load_db()
    now = datetime.now()
    for uid, subs in db["subscribers"].items():
        for sid, sub in subs.items():
            if not isinstance(sub, dict) or sub.get("cancelled"):
                continue
            exp_str = sub.get("expires_at")
            if not exp_str:
                continue
            exp    = datetime.fromisoformat(exp_str)
            days_n = (exp - now).days
            svc    = SERVICES.get(sid, {})
            if days_n in (7, 3, 1) and not sub.get("reminder_sent"):
                try:
                    kb = [[
                        InlineKeyboardButton("🔄 Renouveler",        callback_data=f"service_{sid}"),
                        InlineKeyboardButton("❌ Ne pas renouveler", callback_data=f"cancel_confirm_{sid}"),
                    ]]
                    await ctx.bot.send_message(
                        int(uid),
                        f"⏰ *{svc.get('emoji','')} {svc.get('name',sid)}* expire dans *{days_n} jour{'s' if days_n > 1 else ''} !*\n\n"
                        f"📅 Expiration : *{fmt_date(exp_str)}*\n\nRenouvelez pour continuer 👇",
                        parse_mode="Markdown",
                        reply_markup=InlineKeyboardMarkup(kb)
                    )
                    db["subscribers"][uid][sid]["reminder_sent"] = True
                except Exception as e:
                    logger.warning(f"Rappel client échoué {uid}/{sid}: {e}")
            if days_n < 0 and sub.get("reminder_sent"):
                try:
                    kb = [[InlineKeyboardButton("🔄 Se réabonner", callback_data=f"service_{sid}")]]
                    await ctx.bot.send_message(
                        int(uid),
                        f"😔 *{svc.get('name',sid)} a expiré.*\nRéabonnez-vous !",
                        parse_mode="Markdown",
                        reply_markup=InlineKeyboardMarkup(kb)
                    )
                    db["subscribers"][uid][sid]["reminder_sent"] = False
                except Exception:
                    pass
    save_db(db)

async def notify_admin_expirations(ctx: ContextTypes.DEFAULT_TYPE):
    """Notifie l'admin chaque jour des abonnements expirant sous 3 jours."""
    now      = datetime.now()
    db       = load_db()
    expiring = []
    for uid, subs in db["subscribers"].items():
        for sid in ("youtube", "disney"):
            sub = subs.get(sid)
            if not isinstance(sub, dict) or sub.get("cancelled"):
                continue
            exp_str = sub.get("expires_at")
            if not exp_str:
                continue
            exp    = datetime.fromisoformat(exp_str)
            days_n = (exp - now).days
            if 0 <= days_n <= 3:
                svc = SERVICES.get(sid, {})
                expiring.append(f"{svc.get('emoji','')} `{uid}` {svc.get('name',sid)} — J-{days_n} ({fmt_date(exp_str)})")
    if not expiring:
        return
    msg = f"⚠️ *{len(expiring)} abonnement(s) expirent sous 3 jours :*\n\n" + "\n".join(expiring)
    for aid in ADMIN_IDS:
        try:
            kb = [[InlineKeyboardButton("⚙️ Panel Admin", callback_data="admin")]]
            await ctx.bot.send_message(aid, msg, parse_mode="Markdown",
                                       reply_markup=InlineKeyboardMarkup(kb))
        except Exception as e:
            logger.warning(f"Notif admin échouée: {e}")

# ─────────────────────────────────────────────
# COMMANDES ADMIN
# ─────────────────────────────────────────────

async def cmd_adduser(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return
    try:
        uid      = int(ctx.args[0])
        sid      = ctx.args[1].lower()
        plan_key = ctx.args[2].lower()
        if sid not in SERVICES:
            await update.message.reply_text(f"Services valides: {', '.join(SERVICES.keys())}")
            return
        plan = "Mensuel" if plan_key == "month" else "Annuel"
        days = 31 if plan_key == "month" else 366
        exp  = set_service_sub(uid, sid, plan, days)
        await update.message.reply_text(
            f"✅ {SERVICES[sid]['emoji']} *{SERVICES[sid]['name']}* {plan} pour `{uid}` jusqu'au {fmt_date(exp.isoformat())}.",
            parse_mode="Markdown"
        )
    except Exception:
        await update.message.reply_text("Usage : /adduser <user_id> <service> <month|year>")

async def cmd_removeuser(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return
    try:
        uid = str(int(ctx.args[0]))
        sid = ctx.args[1].lower()
        ok  = cancel_service_sub(int(uid), sid)
        await update.message.reply_text(
            f"✅ {SERVICES.get(sid,{}).get('name',sid)} résilié pour `{uid}`." if ok else "❌ Introuvable.",
            parse_mode="Markdown"
        )
    except Exception:
        await update.message.reply_text("Usage : /removeuser <user_id> <service>")

async def cmd_setaccess(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return
    try:
        uid  = int(ctx.args[0])
        sid  = ctx.args[1].lower()
        info = " ".join(ctx.args[2:])
        set_profile_info(uid, sid, info)
        svc  = SERVICES.get(sid, {})
        await ctx.bot.send_message(
            uid,
            f"🔑 *Vos accès {svc.get('name',sid)} :*\n\n`{info}`\n\n⚠️ _Ne partagez jamais ces informations._",
            parse_mode="Markdown"
        )
        await update.message.reply_text(f"✅ Accès envoyés à `{uid}`.", parse_mode="Markdown")
    except Exception as e:
        await update.message.reply_text(f"Usage : /setaccess <user_id> <service> <info>\nErreur: {e}")

# ─────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────

def main():
    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start",      start))
    app.add_handler(CommandHandler("menu",       menu))
    app.add_handler(CommandHandler("support",      support))
    app.add_handler(CommandHandler("affiliation",  cmd_affiliation))
    app.add_handler(CommandHandler("affiliates",   cmd_affiliates))
    app.add_handler(CommandHandler("genlink",      cmd_genlink))
    app.add_handler(CommandHandler("msg",        cmd_msg))
    app.add_handler(CommandHandler("adduser",    cmd_adduser))
    app.add_handler(CommandHandler("removeuser", cmd_removeuser))
    app.add_handler(CommandHandler("setaccess",  cmd_setaccess))
    app.add_handler(CallbackQueryHandler(button_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_handler))
    jq = app.job_queue
    jq.run_repeating(update_fallback_prices,   interval=3600,  first=10)   # MAJ prix crypto toutes les heures
    jq.run_repeating(check_expirations,        interval=3600,  first=60)
    jq.run_repeating(notify_admin_expirations, interval=86400, first=120)
    logger.info("✅ Bot démarré — YouTube · Disney+ · PayPal · USDT · SOL · XRP")
    app.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()
