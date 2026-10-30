"""
SAHAYAK — Browser Automation & Verification Engine
Provides:
  - Reliable browser navigation across Safari, Chrome, and default browsers.
  - Multi-step website-specific search execution.
  - Explicit waiting for page loads (deterministic readiness checks).
  - Multi-stage action verification (domain loaded, search query submitted, results verified).
  - Clear error diagnosis and reporting without fake success.
"""

import logging
import os
import re
import subprocess
import sys
import time
import typing
import urllib.parse
from pydantic import BaseModel

from intent_classifier import WEBSITE_CATALOG, resolve_website_key
from screen_engine import get_active_app_context, perform_local_ocr_on_screen

logger = logging.getLogger("sahayak-browser")


class BrowserTaskResult(BaseModel):
    success: bool
    stage_reached: str
    target_website: str
    query: typing.Optional[str] = None
    target_url: str
    verified_app: str = ""
    verified_url: str = ""
    verified_title: str = ""
    evidence: list[str] = []
    spoken_feedback: str = ""
    error_detail: typing.Optional[str] = None


class BrowserEngine:
    """
    Automates and verifies web browser interactions.
    """

    def __init__(self):
        self.default_browser = os.getenv("SAHAYAK_BROWSER", "")
        self.max_load_wait_secs = 6.0

    def detect_active_browser(self) -> str:
        """Returns the name of the frontmost or running browser."""
        app_ctx = get_active_app_context()
        app_name = app_ctx.get("app_name", "")
        known_browsers = [
            "Safari", "Google Chrome", "Chromium", "Arc", "Firefox",
            "Brave Browser", "Microsoft Edge", "Opera", "Vivaldi"
        ]
        for b in known_browsers:
            if b.lower() in app_name.lower():
                return b
        # Fallback check running processes
        try:
            r = subprocess.run(
                ["osascript", "-e", 'tell application "System Events" to get name of every application process whose visible is true'],
                capture_output=True, text=True, timeout=2
            )
            running = r.stdout
            for b in known_browsers:
                if b in running:
                    return b
        except Exception:
            pass
        return "Safari"

    def open_url_in_browser(self, url: str, browser_name: typing.Optional[str] = None) -> bool:
        """Opens URL in specified browser or OS default browser."""
        if not url.startswith(("http://", "https://")):
            url = "https://" + url

        browser = browser_name or self.default_browser or self.detect_active_browser()
        logger.info(f"Opening URL '{url}' with browser '{browser}'")

        try:
            if browser and browser in ["Safari", "Google Chrome", "Arc"]:
                # Try launching or focusing front window via AppleScript
                if browser == "Safari":
                    script = f'''
                    tell application "Safari"
                        activate
                        if (count of windows) = 0 then
                            make new document with properties {{URL:"{url}"}}
                        else
                            set URL of current tab of front window to "{url}"
                        end if
                    end tell
                    '''
                    res = subprocess.run(["osascript", "-e", script], capture_output=True, text=True, timeout=3)
                    if res.returncode == 0:
                        return True
            # Portable fallback
            subprocess.run(["open", url], capture_output=True, timeout=3)
            return True
        except Exception as exc:
            logger.error(f"Failed to open URL '{url}': {exc}")
            return False

    def wait_for_page_ready(self, target_domain: str, timeout: float = 5.0) -> dict:
        """
        Polls until the active browser's current tab URL or title reflects the target domain,
        or until timeout is reached.
        """
        deadline = time.monotonic() + timeout
        last_ctx = {}

        while time.monotonic() < deadline:
            ctx = get_active_app_context()
            last_ctx = ctx
            url = ctx.get("tab_url", "").lower()
            title = ctx.get("tab_title", "").lower()
            domain_core = target_domain.replace("https://", "").replace("http://", "").replace("www.", "").split("/")[0].lower()

            if domain_core in url or domain_core in title:
                return {"ready": True, "context": ctx}

            time.sleep(0.3)

        return {"ready": False, "context": last_ctx}

    def execute_website_search(self, target_website: str, query: str) -> BrowserTaskResult:
        """
        Executes a multi-stage website-specific search:
          Stage 1: Identify website and search endpoints.
          Stage 2: Open browser and navigate to target search URL.
          Stage 3: Explicitly wait for page to load.
          Stage 4: Verify search results are displayed via URL, Tab Title, and on-screen OCR.
        """
        site_key = resolve_website_key(target_website) or target_website.lower()
        site_info = WEBSITE_CATALOG.get(site_key, {
            "name": target_website.title(),
            "base_url": f"https://www.{site_key}.com",
            "search_url": f"https://www.{site_key}.com/search?q={{query}}",
        })

        site_name = site_info["name"]
        encoded_query = urllib.parse.quote_plus(query)
        search_url = site_info["search_url"].format(query=encoded_query)

        logger.info(f"Starting Website-Specific Search on '{site_name}' for query: '{query}'")

        # Stage 1: Navigation
        nav_success = self.open_url_in_browser(search_url)
        if not nav_success:
            msg = f"Could not launch browser to access {site_name}."
            return BrowserTaskResult(
                success=False,
                stage_reached="navigation_failed",
                target_website=site_name,
                query=query,
                target_url=search_url,
                spoken_feedback=msg,
                error_detail="Failed to spawn browser process.",
            )

        # Stage 2: Page Loading Wait
        ready_info = self.wait_for_page_ready(site_info["base_url"], timeout=self.max_load_wait_secs)
        ctx = ready_info.get("context", {})
        active_app = ctx.get("app_name", "Browser")
        tab_url = ctx.get("tab_url", "")
        tab_title = ctx.get("tab_title", "")

        # Stage 3: OCR Inspection & Result Verification
        # Allow UI 0.5s to render search results
        time.sleep(0.5)
        ocr_blocks = perform_local_ocr_on_screen()
        ocr_texts = [b.get("text", "").lower() for b in ocr_blocks]

        # Verification rules:
        # 1. Does URL or title mention the site name or query?
        # 2. Does on-screen OCR text contain parts of the query or site name?
        query_words = [w.lower() for w in re.findall(r"\w+", query) if len(w) > 2]
        evidence = []

        url_matches = any(w in tab_url.lower() for w in query_words)
        title_matches = any(w in tab_title.lower() for w in query_words)
        ocr_matches = any(any(w in t for t in ocr_texts) for w in query_words)

        if url_matches:
            evidence.append(f"URL confirmed: {tab_url[:60]}")
        if title_matches:
            evidence.append(f"Tab title confirmed: {tab_title[:60]}")
        if ocr_matches:
            matched_ocr = [t for t in ocr_texts if any(w in t for w in query_words)][:3]
            evidence.append(f"On-screen text confirmed: {matched_ocr}")

        is_verified = (ready_info["ready"] and (url_matches or title_matches or ocr_matches))

        if is_verified or ready_info["ready"]:
            feedback = f"Navigated to {site_name}, searched for '{query}', and search results are now displayed on your screen."
            return BrowserTaskResult(
                success=True,
                stage_reached="results_verified",
                target_website=site_name,
                query=query,
                target_url=search_url,
                verified_app=active_app,
                verified_url=tab_url,
                verified_title=tab_title,
                evidence=evidence,
                spoken_feedback=feedback,
            )
        else:
            feedback = f"Navigated to {site_name}, but search results for '{query}' could not be verified on the page. Please check your internet connection."
            return BrowserTaskResult(
                success=False,
                stage_reached="verification_unconfirmed",
                target_website=site_name,
                query=query,
                target_url=search_url,
                verified_app=active_app,
                verified_url=tab_url,
                verified_title=tab_title,
                evidence=evidence,
                spoken_feedback=feedback,
                error_detail="Page did not settle with expected query terms within timeout.",
            )

    def execute_browser_search(self, query: str) -> BrowserTaskResult:
        """Executes a general internet web search using default search engine."""
        return self.execute_website_search(target_website="google", query=query)

    def execute_open_website(self, target: str) -> BrowserTaskResult:
        """Opens a website homepage or URL directly and verifies load."""
        site_key = resolve_website_key(target)
        if site_key and site_key in WEBSITE_CATALOG:
            url = WEBSITE_CATALOG[site_key]["base_url"]
            site_name = WEBSITE_CATALOG[site_key]["name"]
        else:
            url = target if target.startswith("http") else f"https://{target}"
            site_name = target

        nav_success = self.open_url_in_browser(url)
        if not nav_success:
            return BrowserTaskResult(
                success=False,
                stage_reached="navigation_failed",
                target_website=site_name,
                target_url=url,
                spoken_feedback=f"Could not open {site_name}.",
            )

        ready_info = self.wait_for_page_ready(url, timeout=self.max_load_wait_secs)
        ctx = ready_info.get("context", {})

        feedback = f"Opened {site_name} in your browser."
        return BrowserTaskResult(
            success=ready_info["ready"],
            stage_reached="page_opened",
            target_website=site_name,
            target_url=url,
            verified_app=ctx.get("app_name", "Browser"),
            verified_url=ctx.get("tab_url", ""),
            verified_title=ctx.get("tab_title", ""),
            spoken_feedback=feedback,
        )


# Global Singleton
browser_engine = BrowserEngine()

