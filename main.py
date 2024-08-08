from fastapi import FastAPI, Request, HTTPException
from slack_sdk import WebClient
from slack_sdk.errors import SlackApiError
import requests
import logging
import time
from languages import flag_language_map
from langdetect import detect, DetectorFactory
from dotenv import load_dotenv
import os

load_dotenv()

# Ensure consistent results from the language detection library
DetectorFactory.seed = 0

app = FastAPI()
slack_token = os.getenv('SLACK_TOKEN')
client = WebClient(token=slack_token)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

rapidapi_key = os.getenv('RAPIDAPI_KEY')
rapidapi_host = "google-translator9.p.rapidapi.com"

@app.post("/slack/events")
async def slack_events(request: Request):
    try:
        data = await request.json()
        logger.info(f"Received event: {data}")

        if "type" in data and data["type"] == "url_verification":
            logger.info("URL verification challenge received")
            return {"challenge": data["challenge"]}

        if "event" in data and data["event"]["type"] == "reaction_added":
            event = data["event"]
            reaction = event["reaction"]
            message_ts = event["item"]["ts"]
            channel = event["item"]["channel"]

            country_code = reaction[-2:]
            if country_code in flag_language_map:
                target_language = flag_language_map[country_code]

                try:
                    response = client.conversations_history(channel=channel, latest=message_ts, limit=1, inclusive=True)
                    original_text = response["messages"][0]["text"]

                    # Detect the source language of the message
                    source_language = detect(original_text)

                    # Translate the message
                    translated_text = translate_message(original_text, source_language, target_language)
                    client.chat_postMessage(channel=channel, text=f"Translated: {translated_text}", thread_ts=message_ts)
                except SlackApiError as e:
                    logger.error(f"Error fetching conversation history: {e.response['error']}")

        return {"status": "ok"}
    except Exception as e:
        logger.error(f"Error processing request: {e}")
        raise HTTPException(status_code=400, detail=str(e))

def translate_message(text, source_lang, target_lang):
    api_url = "https://google-translator9.p.rapidapi.com/v2"
    headers = {
        'Content-Type': 'application/json',
        'Accept-Encoding': 'application/gzip',
        'X-RapidAPI-Host': rapidapi_host,
        'X-RapidAPI-Key': rapidapi_key
    }
    data = {
        "q": text,
        "source": source_lang,
        "target": target_lang,
        "format": "text"
    }
    try:
        response = requests.post(api_url, headers=headers, json=data)
        if response.status_code == 429:  # Too many requests
            logger.warning("Rate limit exceeded. Retrying after some time...")
            time.sleep(60)  # Wait for a minute before retrying
            response = requests.post(api_url, headers=headers, json=data)
        response_data = response.json()
        logger.info(f"Translation API response: {response_data}")
        if "data" in response_data and "translations" in response_data["data"]:
            return response_data["data"]["translations"][0]["translatedText"]
        else:
            logger.error(f"Unexpected response structure: {response_data}")
            raise HTTPException(status_code=400, detail=f"Translation API error: {response_data.get('message', 'Unknown error')}")
    except Exception as e:
        logger.error(f"Error calling translation API: {e}")
        raise HTTPException(status_code=400, detail=f"Translation API error: {e}")
