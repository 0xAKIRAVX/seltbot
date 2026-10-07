#!/usr/bin/env python3
"""Interactive session generator — ONLY if the old session ever dies.

Run locally (any PC / Termux):
    python gen_session.py
Enter your phone number + the login code Telegram sends you,
then put the printed SESSION STRING into the TELEGRAM_SESSION secret.
"""
import asyncio

from telethon import TelegramClient
from telethon.sessions import StringSession

API_ID = int(input("API_ID (e.g. 17349): ").strip() or "17349")
API_HASH = input("API_HASH: ").strip()


async def main():
    async with TelegramClient(StringSession(), API_ID, API_HASH) as c:
        s = c.session.save()
        print("\n--- SESSION STRING (SECRET! never share) ---\n")
        print(s)
        print("\n--- put this in the TELEGRAM_SESSION secret ---")


asyncio.run(main())
