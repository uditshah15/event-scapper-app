# main.py
from fastapi import FastAPI, HTTPException, Depends, Header
from playwright.async_api import async_playwright
from bs4 import BeautifulSoup
import re
import logging
import os
from dotenv import load_dotenv
from typing import Optional

# Load environment variables
load_dotenv()

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(
    title="AI Events Scraper API",
    description="API to scrape AI-related events from Microsoft Events page. Requires API key authentication.",
    version="1.0.0"
)

# Get API key from environment
API_KEY = os.getenv("API_KEY")
if not API_KEY:
    raise ValueError("API_KEY environment variable is not set")

async def verify_api_key(x_api_key: Optional[str] = Header(None)):
    """Verify the API key from the request header"""
    if not x_api_key:
        raise HTTPException(status_code=401, detail="API key is required")
    if x_api_key != API_KEY:
        raise HTTPException(status_code=401, detail="Invalid API key")
    return x_api_key

# Keywords to identify AI-related events (case-insensitive)
AI_KEYWORDS = [
    "AI", "Artificial Intelligence", "Machine Learning", "ML",
    "Deep Learning", "Cognitive Services", "Azure AI", "Copilot",
    "Generative AI", "Neural Networks", "Data Science", "Intelligent Apps"
]

@app.get("/ai-events")
async def get_ai_events(api_key: str = Depends(verify_api_key)):
    """
    Scrapes the Microsoft Events page for events related to AI.
    Returns a list of dictionaries, each representing an AI event.
    Requires API key authentication via X-API-Key header.
    """
    url = "https://events.microsoft.com/en-us/allevents/?language=English&clientTimeZone=1"
    events_data = []

    try:
        async with async_playwright() as p:
            # Launching a headless browser for scraping
            # Set headless=False if you want to see the browser UI during scraping
            browser = await p.chromium.launch(headless=True)
            page = await browser.new_page()
            logger.info(f"Navigating to {url}")
            await page.goto(url, wait_until="networkidle")

            # Click "Load next 16 results" button 4 times to load more events
            for i in range(4):
                try:
                    # Look for the "Load next 16 results" button
                    load_more_button = await page.query_selector('button:has-text("Load next 16 results")')
                    if load_more_button:
                        logger.info(f"Clicking 'Load next 16 results' button (attempt {i+1}/4)")
                        await load_more_button.click()
                        # Wait for new content to load
                        await page.wait_for_timeout(5000)  # Wait 5 seconds for content to load
                        # Wait for network to be idle
                        await page.wait_for_load_state('networkidle')
                    else:
                        logger.info(f"No 'Load next 16 results' button found on attempt {i+1}/4")
                        break
                except Exception as e:
                    logger.warning(f"Error clicking load more button on attempt {i+1}/4: {e}")
                    break

            # Scroll to load more events if necessary (Microsoft events page often loads more on scroll)
            # This is a heuristic and might need adjustment based on page behavior
            for _ in range(3): # Scroll 3 times to load more content
                await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                await page.wait_for_timeout(2000) # Wait for content to load after scroll

            html_content = await page.content()
            await browser.close()

        soup = BeautifulSoup(html_content, 'html.parser')

        # Find all event cards using the actual class structure from Microsoft's page
        event_cards = soup.find_all('div', class_='c-card bgcolor-white grideventscroll')

        if not event_cards:
            logger.warning("No event cards found with the specified class. Check HTML structure.")
            # Fallback to a broader search if specific classes aren't found
            event_cards = soup.find_all('div', class_=re.compile(r'card|event', re.IGNORECASE))

        logger.info(f"Found {len(event_cards)} event cards")

        for card in event_cards:
            # Extract title from h3 with class c-heading-6
            title_tag = card.find('h3', class_='c-heading-6')
            
            # Extract date from p with class title-date
            date_tag = card.find('p', class_='title-date')
            
            # Extract description from p with class gridcard-description-min
            description_tag = card.find('p', class_='gridcard-description-min')
            
            # Extract link from the registration button's onclick attribute
            link = "N/A"
            reg_button = card.find('button', {'id': re.compile(r'EventRegistrationButton')})
            if reg_button and reg_button.get('onclick'):
                onclick = reg_button['onclick']
                # Extract URL from onclick="window.open('URL', '_blank')"
                url_match = re.search(r"window\.open\('([^']+)'", onclick)
                if url_match:
                    link = url_match.group(1)

            title = title_tag.get_text(strip=True) if title_tag else "N/A"
            date = date_tag.get_text(strip=True) if date_tag else "N/A"
            description = description_tag.get_text(strip=True) if description_tag else ""

            # Check if any AI keyword is in the title or description (case-insensitive)
            is_ai_event = any(
                re.search(r'\b' + re.escape(keyword) + r'\b', title, re.IGNORECASE) or
                re.search(r'\b' + re.escape(keyword) + r'\b', description, re.IGNORECASE)
                for keyword in AI_KEYWORDS
            )

            if is_ai_event:
                events_data.append({
                    "title": title,
                    "date": date,
                    "description": description,
                    "link": link
                })
                logger.info(f"Found AI event: {title}")
        
        if not events_data:
            logger.info("No AI-related events found after filtering.")

        return {"ai_events": events_data}

    except Exception as e:
        logger.error(f"Error during scraping: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to scrape events: {e}")

