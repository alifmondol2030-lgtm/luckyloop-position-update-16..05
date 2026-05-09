def scrape_jobs():
    try:
        payload = {
            "api_key": SCRAPER_API_KEY,
            "url": TARGET_URL,
            "keep_headers": "true",
        }
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36",
            "Cookie": f"PHPSESSID={PHPSESSID}"
        }
        r = requests.get(
            "http://api.scraperapi.com",
            params=payload,
            headers=headers,
            timeout=60
        )
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
