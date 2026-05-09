import requests
import time
import threading
import os
from bs4 import BeautifulSoup
from datetime import datetime

SERVER_URL      = "https://luckyloop-position-update-16-05.onrender.com/"
PHPSESSID       = os.environ.get("MW_PHPSESSID", "nr5b7jhva7vgt1360to0ps7om9")
SCRAPER_API_KEY = os.environ.get("SCRAPER_API_KEY", "5679a283515dfae539ac18d6f3715dd0")

JOB_NAMES = [
    {"full": "TTV-Data Entry - PC required. Not for mobile phones. (E766-1470)", "short": "1470"},
    {"full": "TTV-Data Entry from images (E502-1033)",                            "short": "1033"},
    {"full": "TTV-Data Entry from images (E1096-1891)",                           "short": "1891"},
    {"full": "TTV-Data Entry from images (E833-1532)",                            "short": "1532"},
    {"full": "TTV-Data Entry - PC required. Not for mobile phones. (E766-2289)",  "short": "2289"},
    {"full": "TTV-Data Entry (E766-1469sv)",                                      "short": "1469"},
    {"full": "TTV-Data Entry from images (E502-1001)",                            "short": "1001"},
]

TARGET_URL = "https://www.microworkers.com/jobs.php?Filter=no&Sort=NEWEST&Id_category=09"

def calc_available(pos_str):
    try:
        cur, total = pos_str.split("/")
        return str(max(int(total) - int(cur), 0))
    except:
        return "-"

def update_status(status, message):
    try:
        requests.post(f"{SERVER_URL}/api/scraper-status", json={
            "status" : status,
            "message": message
        }, timeout=10)
        print(f"[STATUS] {status} | {message}")
    except Exception as e:
        print(f"[Status Error] {e}")

def scrape_jobs():
    try:
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36",
            "Cookie": f"PHPSESSID={PHPSESSID}",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.5",
            "Referer": "https://www.microworkers.com/",
        }
        r = requests.get(TARGET_URL, headers=headers, timeout=30)
        print(f"[Scraper] Status code: {r.status_code}")
        print(f"[Scraper] Response snippet: {r.text[:500]}")

        soup = BeautifulSoup(r.text, "html.parser")
        listings = soup.select(".jobslist")
        count = len(listings)
        print(f"[Scraper] Found {count} listings")

        if count == 0:
            update_status("expired", "⚠️ PHPSESSID Expired! Render এ নতুন Cookie দিন।")
            return

        update_status("ok", f"✅ Running | {count} listings found")

        for job in JOB_NAMES:
            for item in listings:
                name_el = item.select_one(".jobname a")
                pos_el  = item.select_one(".jobdone p")
                if not name_el or not pos_el:
                    continue
                if name_el.get_text(strip=True) == job["full"]:
                    position  = pos_el.get_text(strip=True)
                    available = calc_available(position)
                    link      = name_el.get("href", TARGET_URL)
                    push(job["short"], position, available, link)
                    break
    except Exception as e:
        print(f"[Scraper] Error: {e}")
        update_status("error", f"❌ Error: {str(e)[:80]}")

def push(cid, position, available, link):
    try:
        requests.post(f"{SERVER_URL}/save", json={
            "job_name" : cid,
            "position" : position,
            "available": available,
            "link"     : link
        }, timeout=10)
        print(f"[Scraper] Pushed {cid} pos={position} avail={available}")
    except Exception as e:
        print(f"[Scraper] Push error: {e}")

def scrape_loop():
    print("[Scraper] Starting — checking at sec 2, 4, 33, 35...")
    time.sleep(5)
    CHECK_SECONDS = {2, 4, 33, 35}
    last_checked_sec = -1
    while True:
        sec = datetime.now().second
        if sec in CHECK_SECONDS and sec != last_checked_sec:
            last_checked_sec = sec
            print(f"[Scraper] Checking at :{sec:02d}")
            scrape_jobs()
        time.sleep(0.5)

def start_scraper():
    t = threading.Thread(target=scrape_loop, daemon=True)
    t.start()
