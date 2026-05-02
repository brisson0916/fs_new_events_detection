import requests
from bs4 import BeautifulSoup
from dotenv import load_dotenv
from datetime import datetime, timezone
from pathlib import Path
import json
import os
import logging
from discord_webhook import DiscordWebhook, DiscordEmbed


load_dotenv()

STATE_FILE = Path(__file__).parent / "state.json"
LOG_FILE = Path(__file__).parent / "execution_log.log"
DISCORD_WEBHOOK_URL = os.getenv("DISCORD_WEBHOOK_URL")
FS_EVENTS_URL = os.getenv("FS_EVENTS_URL")
REQUEST_TIMEOUT = 10

logger = logging.getLogger("fs_events_detection")
if not logger.handlers:
    logger.setLevel(logging.INFO)
    handler = logging.FileHandler(LOG_FILE)
    handler.setFormatter(logging.Formatter(
        '%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    ))
    logger.addHandler(handler)

#Get webpage
def fetch_page(url: str) -> str:
    response = requests.get(url, headers={
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }, timeout=REQUEST_TIMEOUT)
    response.raise_for_status()
    return response.text


def parse_events(html: str) -> list[dict]:
    """Returns list of {title, url} dicts for latest 5 events."""
    soup = BeautifulSoup(html, "html.parser")

    # Primary: class-based selector (fragile, depends on CSS class names)
    elements = soup.select("div.event-item-title.type-body-medium.bold.type-mohave")
    selector = "div.event-item-title.type-body-medium.bold.type-mohave"

    # Fallback: URL-based selector (more resilient, relies on /event/ path)
    if not elements:
        elements = soup.select("a[href*='/event/']")
        selector = "a[href*='/event/']"

    if not elements:
        raise ValueError(f"No event elements found on page (tried: {selector})")

    events = []
    for el in elements[:5]:
        title = el.get_text().strip() # Get text from element or its children
        href = el.find('a').get("href") # Get href from anchor if not directly on element
        
        if title:
            if not href:
                events.append({"title": title, "url": None})
            else:
                events.append({"title": title, "url": href})
    if not events:
        logger.error("no events found on page")
    return events


def load_state() -> dict:
    if not STATE_FILE.exists():
        return {"seen_events": [], "last_checked": None}
    with open(STATE_FILE, "r") as f:
        return json.load(f)

def save_state(state: dict) -> None:
    with open(STATE_FILE, "w") as f:
        json.dump(state, f, indent=2)

def send_discord(new_events: list[dict]) -> bool:
    if not DISCORD_WEBHOOK_URL:
        logger.error("DISCORD_WEBHOOK_URL not set in environmental variables, skipping notification")
        return False

    body_lines = []
    for event in new_events:
        body_lines.append(f"{event['title']}\n{event['url']}\n")

    webhook = DiscordWebhook(url=DISCORD_WEBHOOK_URL)
    embed = DiscordEmbed(title="New event(s) in Fung Scholar:", description=str("\n".join(body_lines).strip()))
    webhook.add_embed(embed)
    response = webhook.execute()

    if response.status_code == 200:
        logger.info("Discord notification sent successfully")
        return True
    else:
        logger.error(f"Discord notification failed (status {response.status_code}, {response.text})")
        return False


def main():
    try:
        if not FS_EVENTS_URL:
            logger.error("FS_EVENTS_URL not set in environmental variables, aborting")
            exit(1)
        
        html_text = fetch_page(FS_EVENTS_URL)
        latest_events = parse_events(html_text)
        state = load_state()

        seen_titles = {e["title"] for e in state["seen_events"]}
        new_events = [e for e in latest_events if e["title"] not in seen_titles]

        if not new_events:
            logger.info("No new events")
        else: 
            logger.info(f"New events detected: {[e['title'] for e in new_events]}")
            send_discord(new_events)
            for event in new_events:
                state["seen_events"].append({"title": event["title"], "url": event["url"], "first_seen": datetime.now(timezone.utc).isoformat()})

        state["last_checked"] = datetime.now(timezone.utc).isoformat()
        save_state(state)

    except requests.Timeout:
        logger.error("Error: Request timed out")
        exit(1)
    except requests.RequestException as e:
        logger.error(f"Error fetching page: {e}")
        exit(1)
    except ValueError as e:
        logger.error(f"Error parsing page: {e}")
        exit(1)
    except Exception as e:
        logger.error(f"Unexpected error: {e}")
        exit(1)

if __name__ == "__main__":
    main()