"""Einmaliger Verbindungstest: postet einen Test-Tweet, zeigt den Link und löscht ihn nach Enter wieder.
Kosten: 1 Post (ca. 0,015 $) + 1 Löschen (ca. 0,01 $). Start: python bot/testpost.py"""
import json, time, urllib.request as r
import bot  # nutzt Token-Erneuerung und http() des Bots (bot.py führt beim Import nichts aus)

TEXT = "Bot connection test, will be deleted in a moment. " + time.strftime("%H:%M:%S")
auth = {"Authorization": "Bearer " + bot.token()}
tid = bot.http("https://api.x.com/2/tweets", json.dumps({"text": TEXT}).encode(),
               {**auth, "Content-Type": "application/json"})["data"]["id"]
print("Gepostet: https://x.com/Cliperzcoins711/status/" + tid)
input("Schau ihn dir an, dann Enter zum Löschen ... ")
res = bot.http("https://api.x.com/2/tweets/" + tid, headers=auth, method="DELETE")
print("Gelöscht." if res.get("data", {}).get("deleted") else "Löschen unklar: " + json.dumps(res))
