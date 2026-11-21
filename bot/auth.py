"""One-time local login. Run on YOUR computer: python3 bot/auth.py
Needs env X_CLIENT_ID and X_CLIENT_SECRET. Writes tokens.json (gitignored)."""
import os, json, secrets, hashlib, base64, urllib.parse as u, urllib.request as r
cid, sec = os.environ["X_CLIENT_ID"], os.environ["X_CLIENT_SECRET"]
RED = "https://localhost/callback"
v = secrets.token_urlsafe(64); st = secrets.token_urlsafe(16)
ch = base64.urlsafe_b64encode(hashlib.sha256(v.encode()).digest()).rstrip(b"=").decode()
print("Open:\nhttps://x.com/i/oauth2/authorize?" + u.urlencode(dict(response_type="code", client_id=cid, redirect_uri=RED,
      scope="tweet.read tweet.write users.read offline.access media.write", state=st, code_challenge=ch, code_challenge_method="S256"), quote_via=u.quote))
code = u.parse_qs(u.urlparse(input("Paste full callback URL: ").strip()).query)["code"][0]
auth = base64.b64encode(f"{cid}:{sec}".encode()).decode()
req = r.Request("https://api.x.com/2/oauth2/token", u.urlencode(dict(grant_type="authorization_code", client_id=cid,
      redirect_uri=RED, code_verifier=v, code=code)).encode(), {"Authorization": "Basic " + auth,
      "Content-Type": "application/x-www-form-urlencoded"})
json.dump(json.load(r.urlopen(req)), open("tokens.json", "w")); print("saved tokens.json")
