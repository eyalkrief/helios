
import os
from urllib.parse import urlencode
import requests
from flask import request, session
from database import create_session, delete_session, upsert_user

def google_login_url():
    p = {"client_id": os.environ.get("GOOGLE_CLIENT_ID",""),
         "redirect_uri": os.environ.get("GOOGLE_REDIRECT_URI",""),
         "response_type": "code",
         "scope": "openid email profile",
         "access_type": "offline",
         "prompt": "select_account"}
    return "https://accounts.google.com/o/oauth2/v2/auth?" + urlencode(p)

def handle_google_callback():
    code = request.args.get("code")
    if not code: return None
    try:
        r = requests.post("https://oauth2.googleapis.com/token", data={
            "code": code,
            "client_id": os.environ.get("GOOGLE_CLIENT_ID"),
            "client_secret": os.environ.get("GOOGLE_CLIENT_SECRET"),
            "redirect_uri": os.environ.get("GOOGLE_REDIRECT_URI"),
            "grant_type": "authorization_code"}, timeout=10)
        if not r.ok: return None
        at = r.json().get("access_token")
        u = requests.get("https://www.googleapis.com/oauth2/v2/userinfo",
                         headers={"Authorization": "Bearer "+at}, timeout=10)
        if not u.ok: return None
        info = u.json()
        user = upsert_user(info["id"], info["email"], info.get("name",""), info.get("picture",""))
        session["helios_token"] = create_session(user["user_id"])
        return user
    except Exception as e:
        print("OAuth error:", e)
        return None

def logout():
    t = session.pop("helios_token", None)
    if t: delete_session(t)
