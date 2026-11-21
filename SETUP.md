# Setup on your computer
1. Install Python 3 (python.org). Unzip this folder.
2. Open Terminal (Mac) or Command Prompt (Windows) in the folder.
3. Set your X keys (from console.x.com > your app > Keys and tokens > OAuth 2.0):
   Mac:     export X_CLIENT_ID="your id"  &&  export X_CLIENT_SECRET="your secret"
   Windows: set X_CLIENT_ID=your id   then   set X_CLIENT_SECRET=your secret
4. Log in once:  python3 bot/auth.py   (Windows: python bot\auth.py)
   Open the link, tap Authorize, paste the full https://localhost/callback?... URL back. It creates tokens.json.
5. Test (nothing is posted, dry_run is true):  python3 bot/bot.py
6. Go live: set "dry_run": false in bot/config.json, then run:  python3 bot/run_loop.py
   Keep the computer on. To stop: close the window, or create a file named STOP in this folder.
Never share tokens.json or your Client Secret.
