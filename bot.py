import logging
import os
import csv
import tempfile
from datetime import datetime
from typing import Optional

from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
)
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ContextTypes,
    filters,
)

# Optional: Google Sheets sync
try:
    import gspread
    from google.oauth2.service_account import Credentials

    GSHEETS_AVAILABLE = True
except ImportError:
    GSHEETS_AVAILABLE = False

# Config
BOT_TOKEN = "8101388974:AAEDrrjUy7T6YKZXxTmbdJLEUTD5oY54Bzw"
EXP_KEYWORD = "#r"
UPI_CURRENCY = "INR"
GOOGLE_CREDENTIALS_FILE = os.getenv("GOOGLE_CREDENTIALS_FILE")
GOOGLE_SPREADSHEET_NAME = os.getenv("GOOGLE_SPREADSHEET_NAME", "TripExpenses")

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
logger = logging.getLogger(__name__)


# State helpers
def ensure_chat_data(chat_data: dict):
    chat_data.setdefault("members", [])
    chat_data.setdefault("balances", {})
    chat_data.setdefault("expenses", [])
    chat_data.setdefault("upi_ids", {})
    chat_data.setdefault("current_expense", None)
    chat_data.setdefault("name_to_user_id", {})


async def is_admin(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    try:
        chat = update.effective_chat
        user = update.effective_user
        member = await context.bot.get_chat_member(chat.id, user.id)
        return member.status in ("administrator", "creator")
    except:
        return False


def get_user_name(update):
    user = update.effective_user
    return user.username or user.full_name or user.first_name


# Google Sheets sync
def init_gsheet():
    if not GSHEETS_AVAILABLE or not GOOGLE_CREDENTIALS_FILE:
        return None
    try:
        creds = Credentials.from_service_account_file(
            GOOGLE_CREDENTIALS_FILE,
            scopes=["https://www.googleapis.com/auth/spreadsheets",
                    "https://www.googleapis.com/auth/drive"]
        )
        client = gspread.authorize(creds)
        return client.open(GOOGLE_SPREADSHEET_NAME)
    except Exception as e:
        logger.error(f"Google Sheets init error: {e}")
        return None


GSHEET = None


def append_to_sheet(chat_id, expense):
    global GSHEET
    if not GSHEET:
        GSHEET = init_gsheet()
        if not GSHEET:
            return

    sheet_name = f"Chat_{chat_id}"
    try:
        ws = GSHEET.worksheet(sheet_name)
    except gspread.WorksheetNotFound:
        ws = GSHEET.add_worksheet(sheet_name, rows=1000, cols=10)
        ws.append_row(["When", "Description", "Amount", "Payer", "Group", "Share"])

    ws.append_row([
        expense["timestamp"],
        expense["description"],
        expense["amount"],
        expense["payer"],
        ", ".join(expense["beneficiaries"]),
        expense["share"],
    ])


# Expense computation
def compute_settlements(balances):
    debtors = [(u, -amt) for u, amt in balances.items() if amt < -0.01]
    creditors = [(u, amt) for u, amt in balances.items() if amt > 0.01]
    settlements = []
    while debtors and creditors:
        d_name, d_amt = debtors[0]
        c_name, c_amt = creditors[0]
        amount = min(d_amt, c_amt)
        settlements.append((d_name, c_name, amount))
        d_amt -= amount
        c_amt -= amount
        debtors[0] = (d_name, d_amt)
        creditors[0] = (c_name, c_amt)
        if d_amt <= 0.01:
            debtors.pop(0)
        if c_amt <= 0.01:
            creditors.pop(0)
    return settlements


# Command handlers
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await menu(update, context)


async def menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    ensure_chat_data(context.chat_data)
    keyboard = [
        [InlineKeyboardButton("➕ Add Members", callback_data="add_members")],
        [InlineKeyboardButton("💸 Add Expense", callback_data="add_expense")],
        [InlineKeyboardButton("📊 Summary", callback_data="summary")],
        [InlineKeyboardButton("🧍 My Expenses", callback_data="my_expenses")],
        [InlineKeyboardButton("🆘 Help", callback_data="help")],
    ]
    await update.message.reply_text(
        "🧮 *Trip Manager — Main Menu:*",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="Markdown",
    )


async def setmembers(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_admin(update, context):
        return await update.message.reply_text("Admins only.")
    if not context.args:
        return await update.message.reply_text("Usage: /setmembers A,B,C")

    names = [n.strip() for n in " ".join(context.args).split(",") if n.strip()]
    if len(names) < 2:
        return await update.message.reply_text("Provide at least 2 members!")

    ensure_chat_data(context.chat_data)
    context.chat_data["members"] = names
    context.chat_data["balances"] = {n: 0.0 for n in names}
    return await update.message.reply_text(f"Members set:\n" + "\n".join(names))


async def setup_upi(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_admin(update, context):
        return await update.message.reply_text("Admins only.")
    if len(context.args) != 2:
        return await update.message.reply_text("Use: /setupupi Alice alice@upi")

    member, upi = context.args
    ensure_chat_data(context.chat_data)

    if member not in context.chat_data["members"]:
        return await update.message.reply_text(f"{member} isn't a member.")
    context.chat_data["upi_ids"][member] = upi
    return await update.message.reply_text(f"🔗 {member}'s UPI set to `{upi}`", parse_mode="Markdown")


async def myexpenses(update: Update, context: ContextTypes.DEFAULT_TYPE):
    ensure_chat_data(context.chat_data)
    name = get_user_name(update)
    expenses = context.chat_data["expenses"]
    balances = context.chat_data["balances"]

    total_paid = sum(exp["amount"] for exp in expenses if exp["payer"] == name)
    total_share = sum(exp["share"] for exp in expenses if name in exp["beneficiaries"])

    net = balances.get(name, 0.0)
    status = (
        f"You should *receive* ₹{net:.2f}"
        if net > 0 else
        f"You *owe* ₹{-net:.2f}"
        if net < 0 else
        "You're fully settled"
    )

    msg = (
        f"📒 *Personal Summary — {name}*\n"
        f"- Paid: ₹{total_paid:.2f}\n"
        f"- Share: ₹{total_share:.2f}\n"
        f"- Net: {status}"
    )
    await update.message.reply_text(msg, parse_mode="Markdown")


async def summary(update: Update, context: ContextTypes.DEFAULT_TYPE):
    ensure_chat_data(context.chat_data)
    balances = context.chat_data["balances"]
    settlements = compute_settlements(balances)

    msg = ["💰 *Settlement Summary:*"]
    if not settlements:
        msg.append("Everyone's settled! 🎉")
    else:
        for d, c, amt in settlements:
            msg.append(f"- {d} ➜ {c}: ₹{amt:.2f}")

    # UPI buttons if available
    keyboard = []
    upis = context.chat_data["upi_ids"]
    if upis:
        for d, c, amt in settlements:
            if c in upis:
                link = f"upi://pay?pa={upis[c]}&pn={c}&am={amt:.2f}&cu={UPI_CURRENCY}"
                keyboard.append([InlineKeyboardButton(f"Pay {c} ₹{amt:.0f}", url=link)])

    await update.message.reply_text(
        "\n".join(msg),
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="Markdown",
    )


async def notify(update: Update, context: ContextTypes.DEFAULT_TYPE):
    ensure_chat_data(context.chat_data)
    balances = context.chat_data["balances"]
    settlements = compute_settlements(balances)
    mapping = context.chat_data["name_to_user_id"]

    if not settlements:
        return await update.message.reply_text("🎉 Everyone is settled.")

    count = 0
    for debtor, creditor, amount in settlements:
        if debtor in mapping:
            try:
                await context.bot.send_message(
                    mapping[debtor],
                    f"You owe ₹{amount:.2f} to {creditor}. Please settle soon."
                )
                count += 1
            except:
                pass

    await update.message.reply_text(f"📩 Notifications sent to {count} users.")


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    help_text = (
        "🆘 *Help Menu*\n\n"
        f"➤ `{EXP_KEYWORD}<amount> <description>` — Add an expense\n"
        "➤ `/setmembers A,B,C` — Set members\n"
        "➤ `/addmember Name` — Add new member\n"
        "➤ `/setupupi Name UPI_ID` — Set UPI ID\n"
        "➤ `/summary` — Show settlements\n"
        "➤ `/myexpenses` — Show your expense summary\n"
        "➤ `/notify` — DM users who owe\n"
        "➤ `/menu` — Show menu\n\n"
        "💡 Use this bot in a Telegram group and ensure it's admin."
    )
    await update.message.reply_text(help_text, parse_mode="Markdown")


# Expense message
async def handle_expense(update: Update, context: ContextTypes.DEFAULT_TYPE):
    ensure_chat_data(context.chat_data)
    text = update.message.text.strip()

    if not text.startswith(EXP_KEYWORD):
        return

    try:
        amount_str, desc = text[2:].strip().split(maxsplit=1)
        amount = float(amount_str)
    except:
        return await update.message.reply_text(f"Use: {EXP_KEYWORD}<amount> <description>")

    name = get_user_name(update)
    context.chat_data["name_to_user_id"][name] = update.effective_user.id
    members = context.chat_data["members"]

    if name not in members:
        return await update.message.reply_text(f"{name} isn't a member.")

    ctx = {"payer": name, "amount": amount, "desc": desc, "picked": set()}
    context.chat_data["current_expense"] = ctx

    keyboard = [
        [InlineKeyboardButton(m, callback_data=f"user_{m}") for m in members],
        [InlineKeyboardButton("✔️ Done", callback_data="done"),
         InlineKeyboardButton("❌ Cancel", callback_data="cancel")]
    ]
    await update.message.reply_text(
        f"💸 New Expense!\nPayer: {name}\nAmount: ₹{amount:.2f}\nPick beneficiaries:",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )


# Callback for expense selection
async def callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    data = query.data
    await query.answer()

    ctx = context.chat_data.get("current_expense")

    if data == "cancel":
        context.chat_data["current_expense"] = None
        return await query.edit_message_text("🚫 Expense cancelled.")

    if data == "done":
        if not ctx or not ctx["picked"]:
            return await query.answer("Select at least one.", show_alert=True)

        share = ctx["amount"] / len(ctx["picked"])
        for member in ctx["picked"]:
            if member != ctx["payer"]:
                context.chat_data["balances"][member] -= share
                context.chat_data["balances"][ctx["payer"]] += share

        expense = {
            "timestamp": datetime.utcnow().isoformat(),
            "description": ctx["desc"],
            "amount": ctx["amount"],
            "payer": ctx["payer"],
            "beneficiaries": list(ctx["picked"]),
            "share": share,
        }
        context.chat_data["expenses"].append(expense)
        context.chat_data["current_expense"] = None

        append_to_sheet(update.effective_chat.id, expense)
        return await query.edit_message_text(
            f"🧾 Expense recorded!\nPayer: {ctx['payer']}\nAmount: ₹{ctx['amount']:.2f}",
        )

    if data.startswith("user_"):
        member = data.replace("user_", "")
        ctx["picked"].add(member) if member not in ctx["picked"] else ctx["picked"].remove(member)
        return await query.edit_message_reply_markup(
            InlineKeyboardMarkup([
                [InlineKeyboardButton(m + (" ✔️" if m in ctx["picked"] else ""), callback_data=f"user_{m}") for m in
                 context.chat_data["members"]],
                [InlineKeyboardButton("✔️ Done", callback_data="done"),
                 InlineKeyboardButton("❌ Cancel", callback_data="cancel")]
            ])
        )

    # Menu shortcuts
    if data == "add_members": return await update.effective_message.reply_text("/setmembers A,B,C")
    if data == "summary": return await summary(update, context)
    if data == "help": return await help_command(update, context)
    if data == "my_expenses": return await myexpenses(update, context)
    if data == "add_expense":
        return await update.effective_message.reply_text(f"Use `{EXP_KEYWORD}<amount> <description>`",
                                                         parse_mode="Markdown")


def main():
    app = Application.builder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("menu", menu))
    app.add_handler(CommandHandler("setmembers", setmembers))
    app.add_handler(CommandHandler("setupupi", setup_upi))
    app.add_handler(CommandHandler("myexpenses", myexpenses))
    app.add_handler(CommandHandler("summary", summary))
    app.add_handler(CommandHandler("notify", notify))
    app.add_handler(CommandHandler("help", help_command))

    app.add_handler(MessageHandler(filters.TEXT & filters.Regex(rf"^{EXP_KEYWORD}"), handle_expense))
    app.add_handler(CallbackQueryHandler(callback))

    app.run_polling()


if __name__ == "__main__":
    main()