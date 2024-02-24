#!/usr/bin/env python

# Daniel Mendoza

# Interact with Spotify Web API

import base64
import json
import logging
import os
import random
import redis
import requests
import string
import sys
import urllib
import webbrowser

from http.server import BaseHTTPRequestHandler, HTTPServer
from flask import Flask, render_template, request, redirect, url_for

# Save logging output
logging.basicConfig(filename='./log/output.log',
                    filemode='a',
                    format='%(asctime)s %(name)s %(levelname)s %(message)s',
                    datefmt='%H:%M:%S',
                    level=logging.DEBUG)

# Redis Connection

rd = redis.Redis(host="redis", port=6379, decode_responses=True)
try:
    rd.ping()
except redis.ConnectionError as e:
    sys.exit(f"[Connection Error] - {e}")

# Spotify Credentials

with open("/run/secrets/spotify_uri") as f:
    redirect_uri = f.readline().strip()

with open("/run/secrets/spotify_client_id") as f:
    client_id = f.readline().strip()

with open("/run/secrets/spotify_client_secret") as f:
    client_secret = f.readline().strip()

# Scopes provide Spotify users using third-party apps the confidence that
# only the information they choose to share will be shared, and nothing more.
scope = [
    "user-read-playback-state",
    "user-read-currently-playing",
    "user-modify-playback-state",
    "user-library-read",
    "user-library-modify"
]   # Scope of Spotify API access

scope = " ".join(scope)

# Generate a 16 bit random string
# Provides protection against attacks such as cross-site request forgery
string_16 = string.ascii_letters + string.digits
state = "".join(random.choice(string_16) for i in range(16))

oauth_url = "https://accounts.spotify.com/authorize?"
access_token_url = "https://accounts.spotify.com/api/token"
currently_playing_ep = "https://api.spotify.com/v1/me/player/currently-playing"
available_devices_ep = "https://api.spotify.com/v1/me/player/devices"
save_current_song_ep = "https://api.spotify.com/v1/me/tracks"
verify_saved_song_ep = "https://api.spotify.com/v1/me/tracks/contains"

# Flask application

app = Flask(__name__)

@app.route("/")
def root():
    return redirect(url_for('current_track', action='saved'))

# Request User Authorization

@app.route("/authorize")
def authorize():
    access_token = rd.hget("response_body", "access_token")
    rd.set("auth", "True")
    if not access_token:
        oauth_payload = {
            "response_type": "code",
            "client_id": client_id,
            "client_secret": client_secret,
            "scope": scope,
            "redirect_uri": redirect_uri,
            "state": state
        }
        return redirect(oauth_url + urllib.parse.urlencode(oauth_payload))
    return "ACCESS TOKEN GRANTED"

@app.route("/callback")
def callback():
    auth = rd.get("auth")
    app.logger.info(f"{auth=}")
    if not auth:
        return "AUTH MUST BE GRANTED"
    elif rd.hget("response_body", "access_token"):
        return "AUTH TOKEN ALREADY GRANTED"
    else:
        code = request.args.get("code")
        access_token = get_token(code)
        return redirect(url_for('current_track', action='saved'))
    return "ACCESS TOKEN GRANTED"

# Request Access Token

def get_token(code=None):

    token_payload = {
        "code": code,
        "redirect_uri": redirect_uri,
        "grant_type": "authorization_code"
    }

    base64_credentials = base64.b64encode(f"{client_id}:{client_secret}".encode()).decode("utf-8")

    token_headers = {
        "Authorization": "Basic " + base64_credentials,
        "Content-Type": "application/x-www-form-urlencoded"
    }

    res_token = requests.post(access_token_url, data=token_payload, headers=token_headers)
    logging.info(res_token.status_code)
    dict_res_token = json.loads(res_token.text)
    access_token = dict_res_token["access_token"]
    app.logger.info(type(dict_res_token))
    rd.hset("response_body", mapping=dict_res_token)
    return access_token


# Hit Spotify API Endpoint (currently-playing, devices)

@app.route("/current-track", methods=["GET","POST"])
@app.route("/current-track/<action>", methods=["GET","POST"])
def current_track(action=None):
    button_action = request.form.get('action')
    app.logger.info(f"{action=}")
    app.logger.info(f"[PATH] {action}")
    access_token = rd.hget("response_body", "access_token")
    if not access_token:
        return redirect(url_for('authorize'))

    playing=rd.hgetall("playing")
    artist=playing.get('artist')
    song=playing.get('song')
    track_url=playing.get('track_url')
    track_in_playlist= True if "True" == playing.get('track_in_playlist') else False
    data = playing.get('ids')
    if data:
        data=json.loads(rd.hget("playing", "ids"))

    response = hit_api(currently_playing_ep, access_token)
    status_code = response.status_code
    app.logger.info(f"[STATUS_CODE] {status_code}")
    if status_code == 200:
        json_fmt = json.loads(response.text)
        same_shit = 0
        if song != json_fmt["item"]["name"]:
            same_shit = 1
            song = json_fmt["item"]["name"]
            artist = json_fmt["item"]["artists"]
            if len(artist) > 1:
                artist = " & ".join([name["name"] for name in artist])
            else:
                artist = artist[0]["name"]
            track_url = json_fmt["item"]["external_urls"]["spotify"]
            data = {"ids": [json_fmt["item"]["id"]]}
            playing = {
                    "song": song,
                    "artist": artist,
                    "track_url": track_url,
                    "ids": json.dumps(data)
                    }
            rd.hset("playing", mapping=playing)
            # return redirect(url_for("current_track", action="saved"))
        if button_action == "add":
            track_in_playlist = True
            playing.update({"track_in_playlist": str(track_in_playlist)})
            response = hit_api(save_current_song_ep, access_token, data, "PUT")
            status_code = response.status_code
            app.logger.info(f"[STATUS_CODE] {status_code}")
            if status_code == 200:
                app.logger.info("===== Song added to Liked Songs =====")
        elif button_action == "remove":
            track_in_playlist = False
            playing.update({"track_in_playlist": str(track_in_playlist)})
            response = hit_api(save_current_song_ep, access_token, data, "DELETE")
            status_code = response.status_code
            app.logger.info(f"[STATUS_CODE] {status_code}")
            if status_code == 200:
                app.logger.info("===== Song removed from playlist =====")
        elif action == "saved":
            if same_shit:
                data["ids"] = ",".join(data["ids"])
                response = hit_api(verify_saved_song_ep, access_token, data)
                status_code = response.status_code
                app.logger.info(f"[SAVED STATUS_CODE] {status_code}")
                if response.status_code == 200:
                    track_in_playlist = True if "true" in response.text else False
                    playing.update({"track_in_playlist": str(track_in_playlist)})
                    rd.hset("playing", mapping=playing)
                    app.logger.info(f"[IN_PLAYLIST?] {track_in_playlist}")
                    # app.logger.info(f'PREV ACTION {action}')
                    return render_template(
                            "current-track.html",
                            artist=artist,
                            song=song,
                            track_url=track_url,
                            track_in_playlist=track_in_playlist,
                            action=action)
        app.logger.info(f"[SAVED CACHED]")
        return render_template(
                "current-track.html",
                artist=artist,
                song=song,
                track_url=track_url,
                track_in_playlist=track_in_playlist,
                action=action)
    elif status_code == 204:
        rd.delete("playing")
        return render_template("current-track.html")
    elif status_code == 401:
        rd.flushall()
        return redirect(url_for('authorize'))
    else:
        return str(status_code)
    return redirect(url_for("current_track", action="saved"))

def hit_api(api, access_token=None, data=None, method="GET"):
    headers = {"Authorization": f"Bearer {access_token}"}
    # app.logger.info(f"[HIT API] {api} {headers} {data} {method}")
    app.logger.info(f"[METHOD] {method} {api}")
    if method == "POST":
        response = requests.post(api, headers=headers)
        return response
    elif method == "PUT":
        response = requests.put(api, json=data, headers=headers)
        return response
    elif method == "DELETE":
        response = requests.delete(api, json=data, headers=headers)
        return response
    elif data:
        response = requests.get(api + '?' + urllib.parse.urlencode(data), headers=headers)
        return response
    response = requests.get(api, headers=headers)
    return response

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8888, debug=True)
