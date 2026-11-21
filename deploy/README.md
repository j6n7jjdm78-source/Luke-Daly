# Run the bot 24/7 on a free Linux server
1. Create the free server (see chat for Oracle Cloud Always Free steps). Ubuntu 22.04 or 24.04.
2. Upload and unzip this project, then:  bash deploy/setup.sh
3. Create ~/.config/cliperz-bot/keys.env with:
     X_CLIENT_ID=...        X_CLIENT_SECRET=...
     TELEGRAM_BOT_TOKEN=... TELEGRAM_CHAT_ID=-1004445126820
4. Log in to X once:  python3 bot/auth.py   (open the link, authorize, paste the callback URL back)
5. sudo systemctl start cliperz-bot
IMPORTANT: run the bot in ONE place only. Stop it everywhere else first, or X will invalidate the login.
