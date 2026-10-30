"""
SAHAYAK — Intent Classification Engine
Disambiguates and separates user instructions into distinct intents:
  1. system_search: Search for files, apps, or local content using macOS Spotlight.
  2. browser_search: General internet search using a web browser.
  3. website_search: Open a specified website and search within that website.
  4. open_website: Direct navigation to a website URL or domain.
  5. open_application: Launch a local macOS application.
  6. describe_screen: Describe visible screen content or read text.
  7. sensitive_action: Irreversible or sensitive operations needing confirmation.
  8. computer_control: Standard UI operations (scrolling, hotkeys, clicking).
"""

import logging
import re
import typing
from enum import Enum
from pydantic import BaseModel

logger = logging.getLogger("sahayak-intent")


class IntentType(str, Enum):
    SYSTEM_SEARCH = "system_search"
    BROWSER_SEARCH = "browser_search"
    WEBSITE_SEARCH = "website_search"
    OPEN_WEBSITE = "open_website"
    OPEN_APPLICATION = "open_application"
    DESCRIBE_SCREEN = "describe_screen"
    SENSITIVE_ACTION = "sensitive_action"
    COMPUTER_CONTROL = "computer_control"
    CONVERSATIONAL_AI = "conversational_ai"
    MULTISTEP_TASK = "multistep_task"


class IntentResult(BaseModel):
    intent: IntentType
    query: typing.Optional[str] = None
    target_website: typing.Optional[str] = None
    target_app: typing.Optional[str] = None
    url: typing.Optional[str] = None
    confidence: float = 1.0
    explanation: str = ""


# Known popular websites with standard search URLs
WEBSITE_CATALOG = {
    "youtube": {
        "aliases": ["youtube", "yt", "youtube.com", "u tube"],
        "base_url": "https://www.youtube.com",
        "search_url": "https://www.youtube.com/results?search_query={query}",
        "name": "YouTube",
    },
    "google": {
        "aliases": ["google", "google.com"],
        "base_url": "https://www.google.com",
        "search_url": "https://www.google.com/search?q={query}",
        "name": "Google",
    },
    "wikipedia": {
        "aliases": ["wikipedia", "wiki", "wikipedia.org"],
        "base_url": "https://www.wikipedia.org",
        "search_url": "https://en.wikipedia.org/w/index.php?search={query}",
        "name": "Wikipedia",
    },
    "github": {
        "aliases": ["github", "github.com", "git hub"],
        "base_url": "https://github.com",
        "search_url": "https://github.com/search?q={query}",
        "name": "GitHub",
    },
    "amazon": {
        "aliases": ["amazon", "amazon.com", "amazon.in"],
        "base_url": "https://www.amazon.com",
        "search_url": "https://www.amazon.com/s?k={query}",
        "name": "Amazon",
    },
    "reddit": {
        "aliases": ["reddit", "reddit.com"],
        "base_url": "https://www.reddit.com",
        "search_url": "https://www.reddit.com/search/?q={query}",
        "name": "Reddit",
    },
    "duckduckgo": {
        "aliases": ["duckduckgo", "duck duck go", "ddg"],
        "base_url": "https://duckduckgo.com",
        "search_url": "https://duckduckgo.com/?q={query}",
        "name": "DuckDuckGo",
    },
    "bing": {
        "aliases": ["bing", "bing.com"],
        "base_url": "https://www.bing.com",
        "search_url": "https://www.bing.com/search?q={query}",
        "name": "Bing",
    },
    "twitter": {
        "aliases": ["twitter", "x.com", "x"],
        "base_url": "https://twitter.com",
        "search_url": "https://twitter.com/search?q={query}",
        "name": "Twitter / X",
    },
}

# Known macOS system applications (so they are never misidentified as websites)
MAC_SYSTEM_APPS = {
    "calculator", "notes", "terminal", "system settings", "system preferences",
    "finder", "calendar", "contacts", "mail", "reminders", "maps", "photos",
    "facetime", "messages", "music", "podcasts", "tv", "keynote", "pages",
    "numbers", "preview", "textedit", "activity monitor", "app store",
    "safari", "google chrome", "chrome", "arc", "firefox", "brave", "edge",
    "browser", "default browser", "slack", "vscode", "visual studio code"
}

# Explicit local file/system search indicators
SYSTEM_SEARCH_INDICATORS = [
    r"\bon\s+(?:my\s+)?(?:mac|computer|machine|desktop|laptop|drive)\b",
    r"\bsearch\s+(?:my\s+)?(?:mac|computer|machine|desktop|laptop|drive)\b",
    r"\b(?:find|search)\s+(?:the\s+)?file\b",
    r"\bfile\s+named\b",
    r"\bnamed\s+[a-zA-Z0-9_\-\.]+\.[a-zA-Z0-9]+\b",
    r"\bspotlight\b",
    r"\bsearch\s+(?:my\s+)?(?:files|documents|downloads|folder)\b",
    r"\blocally\b",
]

# Sensitive operations patterns
SENSITIVE_PATTERNS = [
    r"\bdelete\b",
    r"\bremove\b",
    r"\berase\b",
    r"\btrash\b",
    r"\bformat\b",
    r"\bpurchase\b",
    r"\bbuy\b",
    r"\bcheckout\b",
    r"\bpay\b",
    r"\bsend\s+(email|message|text|mail)\b",
    r"\bempty\s+trash\b",
    r"\buninstall\b",
]


def resolve_website_key(text: str) -> typing.Optional[str]:
    """Check if text contains a reference to a known website."""
    lower = text.lower()
    for key, info in WEBSITE_CATALOG.items():
        for alias in info["aliases"]:
            # Match whole word or domain
            pattern = r"(?:^|\s|\b)" + re.escape(alias) + r"(?:\b|\s|$)"
            if re.search(pattern, lower):
                return key
    return None


def clean_query(q: str) -> str:
    """Strip common conversational prefixes and punctuation from search query."""
    q = q.strip().strip("'\"").strip()
    # Strip leading "for ", "about ", "videos of ", "the ", etc.
    q = re.sub(r"^(?:for|about|me|videos?\s+of|tutorials?\s+on|the)\s+", "", q, flags=re.IGNORECASE)
    # Strip trailing punctuation
    q = re.sub(r"[\.\?!]+$", "", q).strip()
    return q


def classify_intent(text: str) -> IntentResult:
    """
    Rule-based deterministic classifier that implements the 5 distinct search/navigation intents
    with high precision across various natural language phrasings.
    """
    raw = text.strip()
    lower = raw.lower()

    # 1. Sensitive operations
    for pat in SENSITIVE_PATTERNS:
        if re.search(pat, lower):
            return IntentResult(
                intent=IntentType.SENSITIVE_ACTION,
                query=raw,
                explanation="Operation involves sensitive or irreversible action requiring confirmation.",
            )

    # 2. Describe screen
    if any(q in lower for q in ["what is on my screen", "describe this", "describe the screen", "read this text", "read the text", "what's on my screen", "explain this window"]):
        return IntentResult(
            intent=IntentType.DESCRIBE_SCREEN,
            query=raw,
            explanation="Request to describe or read visible screen content.",
        )

    # 3. Multistep Task Workflows (Sequential Multi-action)
    # Examples:
    #   "Open YouTube, search for Python tutorials, find a beginner tutorial, summarize it and save to Notes."
    #   "Open Safari, then open Notes and write down my next three tasks."
    #   "Find my project PDF, read it and tell me its main points."
    #   "Open Google, search for AI developments, collect the main points and explain them."
    is_open_browser_search = bool(re.match(r"^open\s+(?:the\s+)?browser\s+and\s+search\s+", lower))
    has_seq_conjunction = bool(re.search(r"\b(?:then|and\s+then|after\s+that)\b", lower))
    has_notes_chain = ("notes" in lower and any(w in lower for w in ["write", "save", "tasks", "create"])) and any(w in lower for w in ["open", "search", "find", "summarize", "read"])
    has_summarize_chain = any(w in lower for w in ["summarize", "main points", "collect the main"]) and any(w in lower for w in ["open", "search", "find", "pdf", "read", "inspect", "google", "youtube"])
    has_read_and_tell = bool(re.search(r"\bread\s+(?:it|this|the\s+pdf|my\s+pdf)\s+and\s+(?:tell|summarize|explain)\b", lower))

    if not is_open_browser_search and (has_seq_conjunction or has_notes_chain or has_summarize_chain or has_read_and_tell):
        return IntentResult(
            intent=IntentType.MULTISTEP_TASK,
            query=raw,
            explanation=f"Multi-step task workflow: '{raw}'.",
        )

    # 4. Conversational AI & General Knowledge
    # Questions, explanations, learning plans, coding advice, error diagnostics
    conversational_patterns = [
        r"^(?:hello\s+sahayak|hi\s+sahayak|hello\s+sahay|hey\s+sahay|sahayak|sahay)[,\s]*$",
        r"\b(?:explain|what\s+is|what\s+are|what's|difference\s+between|how\s+does|how\s+do\s+i|tell\s+me\s+about|why\s+is|who\s+is)\b",
        r"\b(?:create|generate|write|make)\s+(?:a|an|me\s+a)?\s+.*(?:plan|guide|routine|schedule|roadmap|tutorial|essay|code|program|script|summary)\b",
        r"\b(?:learning\s+plan|study\s+plan)\b",
        r"\b(?:organize\s+my\s+work|plan\s+my\s+day|help\s+me\s+(?:learn|understand|write|organize))\b",
        r"\b(?:don't\s+understand\s+this\s+error|explain\s+(?:this\s+)?error|what\s+does\s+this\s+mean|fix\s+this\s+error)\b",
    ]
    is_conversational = any(re.search(pat, lower) for pat in conversational_patterns)
    # Check if not looking for a local file
    if is_conversational and not any(w in lower for w in ["file named", "search my mac", "on my mac", "on my computer"]):
        # Also ensure it's not a direct app opening like "open calculator"
        if not re.match(r"^(?:open|launch)\s+[a-zA-Z0-9\s]+$", lower):
            return IntentResult(
                intent=IntentType.CONVERSATIONAL_AI,
                query=raw,
                explanation=f"Conversational AI inquiry: '{raw}'.",
            )

    # 3. System Search (Mac Spotlight / File search)
    # Check if explicitly targeting local Mac files/folders/Spotlight
    is_system_search = False
    for pat in SYSTEM_SEARCH_INDICATORS:
        if re.search(pat, lower):
            is_system_search = True
            break

    if is_system_search:
        # Extract filename or search query
        # Patterns like: "find the file named project.pdf on my Mac"
        m_file = re.search(r"(?:file\s+named|named)\s+([a-zA-Z0-9_\-\.]+(?:\.[a-zA-Z0-9]+)?)", raw, re.IGNORECASE)
        if m_file:
            query = m_file.group(1).strip()
        else:
            # Pattern like "find X on my mac" or "search my mac for X"
            m_search = re.search(r"(?:find|search(?:\s+my\s+mac)?\s+for)\s+(.+?)(?:\s+on\s+my\s+mac|\s+on\s+my\s+computer|$)", raw, re.IGNORECASE)
            if m_search:
                query = m_search.group(1).strip()
            else:
                query = clean_query(raw)
        return IntentResult(
            intent=IntentType.SYSTEM_SEARCH,
            query=clean_query(query),
            explanation=f"Searching local Mac files via Spotlight for '{query}'.",
        )

    # 4. Website-Specific Search
    # Check if a specific website is mentioned in conjunction with a search/find/lookup request
    # Natural language phrasings:
    #   "Open the browser and search YouTube for Python tutorials."
    #   "Open YouTube and search for Python tutorials."
    #   "Go to YouTube and find music."
    #   "Can you look up music on YouTube?"
    #   "Search YouTube for music."
    #   "Find me music videos on YouTube."
    #   "Search for music on YouTube."
    #   "Search on YouTube for music."

    matched_site_key = resolve_website_key(lower)

    if matched_site_key:
        site_info = WEBSITE_CATALOG[matched_site_key]
        site_name = site_info["name"]

        # Check if the user is asking to search / find / look up content on this website
        search_triggers = ["search", "find", "look up", "lookup", "videos", "tutorials", "news", "songs", "tracks", "courses"]
        is_search_intent = any(trig in lower for trig in search_triggers)

        if is_search_intent:
            query = ""
            # Pattern A: "search [site] for [query]" or "search on [site] for [query]"
            m_a = re.search(rf"search\s+(?:on\s+)?(?:the\s+)?{matched_site_key}\s+for\s+(.+)", lower)
            if m_a:
                query = m_a.group(1)
            # Pattern B: "open [site] and (?:search|find|look up)\s+(?:for\s+)?(.+)"
            if not query:
                m_b = re.search(rf"(?:open|go\s+to)\s+(?:the\s+browser\s+and\s+)?(?:the\s+)?{matched_site_key}\s+and\s+(?:search|find|look\s+up)\s+(?:for\s+)?(.+)", lower)
                if m_b:
                    query = m_b.group(1)
            # Pattern C: "open the browser and search [site] for (.+)"
            if not query:
                m_c = re.search(rf"open\s+(?:the\s+)?browser\s+and\s+search\s+(?:on\s+)?{matched_site_key}\s+for\s+(.+)", lower)
                if m_c:
                    query = m_c.group(1)
            # Pattern D: "look up [query] on [site]" or "find [query] on [site]"
            if not query:
                m_d = re.search(rf"(?:look\s+up|find|search\s+for)\s+(.+?)\s+on\s+(?:the\s+)?{matched_site_key}", lower)
                if m_d:
                    query = m_d.group(1)
            # Pattern E: "find me [query] on [site]"
            if not query:
                m_e = re.search(rf"find\s+me\s+(.+?)\s+on\s+(?:the\s+)?{matched_site_key}", lower)
                if m_e:
                    query = m_e.group(1)
            # Pattern F: "search [site] [query]"
            if not query:
                m_f = re.search(rf"search\s+{matched_site_key}\s+(.+)", lower)
                if m_f:
                    query = m_f.group(1)

            query = clean_query(query) if query else ""
            if query:
                return IntentResult(
                    intent=IntentType.WEBSITE_SEARCH,
                    target_website=matched_site_key,
                    query=query,
                    url=site_info["search_url"].format(query=query.replace(" ", "+")),
                    explanation=f"Searching for '{query}' specifically on {site_name}.",
                )

        # If site is mentioned without a search query -> open_website
        # e.g. "Open YouTube", "Go to youtube.com", "Open Google"
        m_just_open = re.search(rf"(?:open|go\s+to|navigate\s+to|launch)\s+(?:the\s+)?{matched_site_key}", lower)
        if m_just_open:
            return IntentResult(
                intent=IntentType.OPEN_WEBSITE,
                target_website=matched_site_key,
                url=site_info["base_url"],
                explanation=f"Navigating to {site_name} homepage.",
            )

    # 5. General Browser Search (search the web / internet)
    # Examples:
    #   "Search the web for the best Python courses."
    #   "Search the internet for weather tomorrow."
    #   "Look up online how to bake sourdough."
    #   "Web search for machine learning."
    m_web_search = re.search(
        r"(?:search\s+(?:the\s+)?(?:web|internet)|search\s+online|web\s+search|google|look\s+up\s+online|look\s+up\s+on\s+the\s+(?:web|internet)|find\s+online)\s+(?:for\s+)?(.+)",
        lower
    )
    if m_web_search:
        query = clean_query(m_web_search.group(1))
        return IntentResult(
            intent=IntentType.BROWSER_SEARCH,
            query=query,
            target_website="google",
            url=f"https://www.google.com/search?q={query.replace(' ', '+')}",
            explanation=f"Searching the web for '{query}' using Google.",
        )

    # Also handle "look up [query] online" or "search for [query] on the web"
    m_look_up_online = re.search(r"(?:look\s+up|search\s+for|find)\s+(.+?)\s+(?:online|on\s+the\s+web|on\s+the\s+internet)$", lower)
    if m_look_up_online:
        query = clean_query(m_look_up_online.group(1))
        return IntentResult(
            intent=IntentType.BROWSER_SEARCH,
            query=query,
            target_website="google",
            url=f"https://www.google.com/search?q={query.replace(' ', '+')}",
            explanation=f"Searching the web for '{query}' using Google.",
        )

    # 6. Direct Website Navigation (URLs or domains with .com, .org, .io, etc.)
    # Examples: "open https://news.ycombinator.com", "go to wikipedia.org", "open reddit.com"
    m_url = re.search(r"(?:open|go\s+to|navigate\s+to)\s+(?:https?://)?([a-zA-Z0-9\-\.]+\.(?:com|org|net|io|ai|gov|edu|dev|co|in)[a-zA-Z0-9_\-\./\?]*)", lower)
    if m_url:
        domain_part = m_url.group(1).strip()
        full_url = domain_part if domain_part.startswith("http") else f"https://{domain_part}"
        return IntentResult(
            intent=IntentType.OPEN_WEBSITE,
            url=full_url,
            explanation=f"Opening website {full_url}.",
        )

    # 7. Open Application
    # Examples: "Open Calculator", "Open Notes", "Open Safari", "Open the browser"
    m_app = re.search(r"(?:open|launch)\s+(?:the\s+)?([a-zA-Z0-9\s]+)", lower)
    if m_app:
        candidate_app = m_app.group(1).strip()
        # If candidate is "browser", resolve to default browser
        if candidate_app in ["browser", "web browser", "internet browser", "safari", "chrome", "google chrome"]:
            return IntentResult(
                intent=IntentType.OPEN_APPLICATION,
                target_app=candidate_app,
                explanation="Opening default web browser.",
            )
        # Check against known Mac apps or non-search instructions
        if candidate_app in MAC_SYSTEM_APPS or (not any(w in candidate_app for w in ["search", "find", "look up"])):
            return IntentResult(
                intent=IntentType.OPEN_APPLICATION,
                target_app=candidate_app.title(),
                explanation=f"Launching application {candidate_app.title()}.",
            )

    # 8. Standard Computer Control
    if "scroll down" in lower:
        return IntentResult(intent=IntentType.COMPUTER_CONTROL, query="scroll_down", explanation="Scroll down.")
    if "scroll up" in lower:
        return IntentResult(intent=IntentType.COMPUTER_CONTROL, query="scroll_up", explanation="Scroll up.")
    if "close" in lower:
        return IntentResult(intent=IntentType.COMPUTER_CONTROL, query="close_window", explanation="Close active window.")

    # Default fallback
    return IntentResult(
        intent=IntentType.COMPUTER_CONTROL,
        query=raw,
        explanation=f"General instruction: '{raw}'.",
    )
