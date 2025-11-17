# TripWise Bot 🤖💸

A Telegram bot that simplifies expense tracking and splitting during trips or group activities. The bot automates expense logging, fair splitting, settlement reminders, and can optionally sync with Google Sheets — all through chat commands in your group.

## 🚀 Live Bot Available!

You can start using the deployed bot immediately:

🔍 Search on Telegram: **`tripwise_split_bot`** 
(This bot is already deployed and configured to handle trips in real-time.)

## 🪄 Features

- **Chat-based expense entry** using `#r<amount> <description>`
- **Beneficiary selection** via inline buttons
- **UPI payment buttons** for easy settlement
- **Google Sheets sync** for record keeping (optional)
- **Personalized commands** like `/summary`, `/myexpenses`, `/notify`
- **Admin control**: `/lockbot`, `/resettrip`, `/setmembers` and more

## 🔧 Commands Overview

- `#r100 Dinner`  → Log an expense
- `/setmembers Alice,Bob`  → Set group members
- `/setupupi Bob bob@upi`  → Add UPI for settlement
- `/summary` → Shows who owes whom
- `/myexpenses` → Shows your share and balance
- `/notify` → Sends private reminders to debtors

## 🛠️ Tech Stack

- Python
- python-telegram-bot
- UPI deep link support
- Optional Google Sheets integration
- Hosted on Render (24/7 deployment)

## 📦 Installation (For Custom Setup)

If you want to run your own version of TripWise Bot:

### 1. Create a Telegram Bot via BotFather
- Open Telegram and search for `BotFather`
- Run the command: `/newbot`
- Give it a name and username (e.g., `TripWiseBot`)
- Copy the token shown (⚠️ **keep it private**)

> Example Token: `123456789:ABCDefghIJKlmnopQRstUvWxyz0123456`

---

### 2. Disable Privacy Mode
For the bot to read messages in the group (like `#r100 Dinner`), you **must disable privacy mode**:

- In BotFather, type: `/mybots`
- Select your bot → `Bot Settings` → `Group Privacy` → `Turn off`
  
Privacy OFF means your bot can read all messages in a group — required for expense triggers.

---

### 3. Update Access Token in Code
Replace the token in your `bot.py` file:

```python
BOT_TOKEN = "YOUR_BOT_TOKEN_HERE"
