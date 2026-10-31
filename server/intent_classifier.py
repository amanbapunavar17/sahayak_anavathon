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
    TAKE_PHOTO = "take_photo"
    CLICK_ELEMENT = "click_element"
    MOUSE_CONTROL = "mouse_control"
    LANGUAGE_SWITCH = "language_switch"


class IntentResult(BaseModel):
    intent: IntentType
    query: typing.Optional[str] = None
    target_website: typing.Optional[str] = None
    target_app: typing.Optional[str] = None
    target_bundle_id: typing.Optional[str] = None
    url: typing.Optional[str] = None
    target_element: typing.Optional[str] = None
    click_type: str = "single"  # single, double, right, triple
    button: str = "left"        # left, right, middle
    x: typing.Optional[int] = None
    y: typing.Optional[int] = None
    confidence: float = 1.0
    explanation: str = ""
    language: typing.Optional[str] = None


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
    "browser", "default browser", "slack", "vscode", "visual studio code",
    "camera", "photo booth"
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


def parse_mouse_and_click_intent(raw: str, lower: str) -> typing.Optional[IntentResult]:
    """
    Parses mouse movement and button click instructions into structured CLICK_ELEMENT
    and MOUSE_CONTROL intents with target element names, click types, or coordinates.
    """
    # Exclude conversational questions
    if any(lower.startswith(q) for q in ["how do i", "how to", "why does", "what is", "tell me about", "explain"]):
        return None

    # Check for coordinate pattern: e.g. "at 450, 300", "(450, 300)", "at 450 300", "x=450 y=300"
    coord_x, coord_y = None, None
    m_coord = re.search(r"(?:at\s+|coordinate[s]?\s+|position\s+|\()?(\d{1,4})\s*(?:,\s*|\s+and\s+|\s+)(\d{1,4})\)?", lower)
    if m_coord:
        try:
            coord_x = int(m_coord.group(1))
            coord_y = int(m_coord.group(2))
        except (ValueError, IndexError):
            pass

    # 1. Double Click
    if re.search(r"\bdouble\s*[- ]?click\b", lower):
        target = re.sub(r".*?\bdouble\s*[- ]?click(?:\s+on|\s+at)?(?:\s+the)?(?:\s+button)?(?:\s+named|\s+called)?\s*", "", lower).strip()
        target = re.sub(r"^(?:the\s+)?button\s+", "", target)
        target = re.sub(r"\s+(?:button|icon|tab|link|field|box)$", "", target)
        target = target.strip(" .,;:-_!?()[]'\"`")
        if target in ("here", "current", "this", "now", "") and coord_x is None:
            target = None
        return IntentResult(
            intent=IntentType.CLICK_ELEMENT,
            query=raw,
            target_element=target if target else None,
            click_type="double",
            button="left",
            x=coord_x,
            y=coord_y,
            explanation=f"Double clicking {target or 'at current position'}.",
        )

    # 2. Right Click
    if re.search(r"\bright\s*[- ]?click\b", lower):
        target = re.sub(r".*?\bright\s*[- ]?click(?:\s+on|\s+at)?(?:\s+the)?(?:\s+button)?(?:\s+named|\s+called)?\s*", "", lower).strip()
        target = re.sub(r"^(?:the\s+)?button\s+", "", target)
        target = re.sub(r"\s+(?:button|icon|tab|link|field|box)$", "", target)
        target = target.strip(" .,;:-_!?()[]'\"`")
        if target in ("here", "current", "this", "now", "") and coord_x is None:
            target = None
        return IntentResult(
            intent=IntentType.CLICK_ELEMENT,
            query=raw,
            target_element=target if target else None,
            click_type="right",
            button="right",
            x=coord_x,
            y=coord_y,
            explanation=f"Right clicking {target or 'at current position'}.",
        )

    # 3. Triple Click
    if re.search(r"\btriple\s*[- ]?click\b", lower):
        target = re.sub(r".*?\btriple\s*[- ]?click(?:\s+on|\s+at)?(?:\s+the)?(?:\s+button)?(?:\s+named|\s+called)?\s*", "", lower).strip()
        target = re.sub(r"\s+(?:button|icon|tab|link|field|box)$", "", target).strip(" .,;:-_!?()[]'\"`")
        return IntentResult(
            intent=IntentType.CLICK_ELEMENT,
            query=raw,
            target_element=target if target else None,
            click_type="triple",
            button="left",
            x=coord_x,
            y=coord_y,
            explanation=f"Triple clicking {target or 'at current position'}.",
        )

    # 4. Mouse movement / Cursor glide
    if re.search(r"\b(?:move\s+(?:the\s+)?(?:mouse|cursor)|glide\s+(?:the\s+)?(?:mouse|cursor)|hover\s+(?:on|over))\b", lower):
        target = re.sub(r".*?\b(?:move\s+(?:the\s+)?(?:mouse|cursor)|glide\s+(?:the\s+)?(?:mouse|cursor)|hover\s+(?:on|over))(?:\s+to|\s+over|\s+at)?(?:\s+the)?\s*", "", lower).strip()
        target = re.sub(r"\s+(?:button|icon|tab|link|field|box)$", "", target).strip(" .,;:-_!?()[]'\"`")
        return IntentResult(
            intent=IntentType.MOUSE_CONTROL,
            query=raw,
            target_element=target if target else None,
            x=coord_x,
            y=coord_y,
            explanation=f"Moving mouse cursor to {target or 'specified location'}.",
        )

    # 5. Single Click / Button Click / Press button / Tap button
    is_click_pattern = bool(re.search(
        r"^(?:please\s+)?(?:click(?:\s+on|\s+at)?|press\s+(?:the\s+)?|tap\s+(?:the\s+)?|single\s+click(?:\s+on)?)\s+",
        lower
    )) or lower in ("click", "click here", "single click", "click on it", "click it")

    if not is_click_pattern:
        if re.search(r"\bclick\s+(?:the\s+)?button\b", lower) or re.search(r"\bbutton\s+click\b", lower):
            is_click_pattern = True

    if is_click_pattern:
        target = re.sub(r"^(?:please\s+)?(?:click(?:\s+on|\s+at)?|press|tap|single\s+click(?:\s+on)?)\s+", "", lower).strip()
        target = re.sub(r"^(?:the\s+)?button\s+(?:named\s+|called\s+)?", "", target)
        target = re.sub(r"^(?:the\s+)", "", target)
        target = re.sub(r"\s+(?:button|icon|tab|link|field|box)$", "", target)
        target = target.strip(" .,;:-_!?()[]'\"`")

        if coord_x is not None and coord_y is not None:
            target = re.sub(r"(?:at\s+|\()?\s*\d{1,4}\s*(?:,\s*|\s+and\s+|\s+)\d{1,4}\)?", "", target).strip(" .,;:-_!?()[]'\"`")

        if target in ("here", "current", "this", "now", "it", "click", ""):
            target = None

        return IntentResult(
            intent=IntentType.CLICK_ELEMENT,
            query=raw,
            target_element=target if target else None,
            click_type="single",
            button="left",
            x=coord_x,
            y=coord_y,
            explanation=f"Clicking {target or 'at coordinates' if coord_x is not None else 'at current cursor position'}.",
        )

    return None


def classify_intent(text: str) -> IntentResult:
    """
    Rule-based deterministic classifier that implements the 5 distinct search/navigation intents
    with high precision across various natural language phrasings.
    """
    raw = text.strip()
    lower = raw.lower()

    # 0. Language Switch intent
    lang_patterns = [
        (
            r"\b(?:switch|change|talk|speak|respond|reply|translate|converse|use|tell\s+me)\b.*\bkannada\b"
            r"|\bkannada\s+(?:language|please|only|mode)\b"
            r"|\b(?:in\s+kannada|to\s+kannada)\b"
            r"|\b(?:kannadadalli|kannada\s+mathadi|kannada\s+bheku|kannadadalli\s+mathadi)\b"
            r"|(?:ಕನ್ನಡ|ಕನ್ನಡದಲ್ಲಿ|ಮಾತನಾಡು|ಹೇಳು)",
            "kn"
        ),
        (
            r"\b(?:switch|change|talk|speak|respond|reply|translate|converse|use|tell\s+me)\b.*\benglish\b"
            r"|\benglish\s+(?:language|please|only|mode)\b"
            r"|\b(?:in\s+english|to\s+english)\b",
            "en-US"
        ),
        (
            r"\b(?:switch|change|talk|speak|respond|reply|translate|converse|use|tell\s+me)\b.*\bhindi\b"
            r"|\bhindi\s+(?:language|please|only|mode)\b"
            r"|\b(?:in\s+hindi|to\s+hindi)\b"
            r"|\b(?:hindi\s+mein|hindi\s+bolo)\b",
            "hi"
        ),
    ]
    for pat, lang_code in lang_patterns:
        if re.search(pat, lower):
            return IntentResult(
                intent=IntentType.LANGUAGE_SWITCH,
                query=raw,
                language=lang_code,
                explanation=f"User requested switching language to {lang_code}."
            )

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

    # 2b. Camera and Photo Capture Intent
    is_take_photo = bool(re.search(
        r"\b(?:take\s+(?:a\s+)?(?:picture|photo|selfie|snapshot)|capture\s+(?:a\s+)?(?:picture|photo)|snap\s+(?:a\s+)?(?:picture|photo)|open\s+(?:the\s+)?camera\s+and\s+take\s+(?:a\s+)?(?:picture|photo))\b",
        lower
    ))
    has_camera_multistep = ("camera" in lower or "picture" in lower or "photo" in lower) and any(w in lower for w in ["notes", "then", "after that", "tell me where", "where the picture was saved"])
    if is_take_photo and not has_camera_multistep:
        return IntentResult(
            intent=IntentType.TAKE_PHOTO,
            query=raw,
            target_app="Photo Booth",
            explanation="Autonomous camera capture workflow using Photo Booth.",
        )

    # 3. Conversational AI & General Knowledge
    # Questions, explanations, learning plans, coding advice, error diagnostics, greetings, advice
    conversational_patterns = [
        r"^(?:hello|hi|hey)\s+(?:sahayak|sahay|sahayaka)[,\s!]*$",
        r"^(?:sahayak|sahay|sahayaka)[,\s!]*$",
        r"^(?:hello|hi|hey|good\s+morning|good\s+afternoon|good\s+evening|namaste|namaskara)[,\s!]*$",
        r"\b(?:explain|what\s+is|what\s+are|what's|difference\s+between|how\s+does|how\s+do\s+i|tell\s+me\s+about|why\s+is|who\s+is|who\s+are\s+you|who\s+made\s+you)\b",
        r"\b(?:where\s+is|where\s+are|when\s+was|when\s+is|which\s+is|whose)\b",
        r"\b(?:can\s+you\s+explain|could\s+you\s+explain|can\s+you\s+tell\s+me|could\s+you\s+tell\s+me|help\s+me\s+with|how\s+can\s+i|do\s+you\s+know|do\s+you\s+have)\b",
        r"\b(?:create|generate|write|make)\s+(?:a|an|me\s+a)?\s+.*(?:plan|guide|routine|schedule|roadmap|tutorial|essay|code|program|script|summary|story|poem|recipe|list)\b",
        r"\b(?:learning\s+plan|study\s+plan)\b",
        r"\b(?:organize\s+my\s+work|plan\s+my\s+day|help\s+me\s+(?:learn|understand|write|organize))\b",
        r"\b(?:don't\s+understand\s+this\s+error|explain\s+(?:this\s+)?error|what\s+does\s+this\s+mean|fix\s+this\s+error)\b",
        r"\b(?:give\s+me|suggest|recommend|advise|tell\s+me\s+(?:a|some)?)\b",
        r"[\u0c80-\u0cff]",  # Any Kannada text is conversational by default
        r"[\u0900-\u097f]",  # Any Devanagari text is conversational by default
    ]
    # Check if this is an action command despite starting with polite phrasing or question mark
    is_action_command = bool(
        resolve_website_key(lower)
        or any(w in lower for w in [
            "look up", "search for", "find me", "search youtube", "search google",
            "open ", "launch ", "click ", "press ", "tap ", "type ", "scroll ",
            "delete ", "create a folder", "move files", "system settings", "brightness"
        ])
    )
    is_conversational = (
        (any(re.search(pat, lower) for pat in conversational_patterns) or re.search(r"\?$", lower))
        and not is_action_command
    )
    if is_conversational and not any(w in lower for w in ["file named", "search my mac", "on my mac", "on my computer"]):
        if not re.match(r"^(?:open|launch)\s+[a-zA-Z0-9\s]+$", lower):
            return IntentResult(
                intent=IntentType.CONVERSATIONAL_AI,
                query=raw,
                explanation=f"Conversational AI inquiry: '{raw}'.",
            )

    # 4. Multistep Task Workflows (Sequential Multi-action)
    # Examples:
    #   "Open YouTube, search for Python tutorials, find a beginner tutorial, summarize it and save to Notes."
    #   "Open Safari, then open Notes and write down my next three tasks."
    #   "Open Safari, search Google for artificial intelligence and return to Notes."
    #   "Find the latest file in Downloads and open it."
    #   "Open System Settings and change the display brightness."
    #   "Open Safari, visit Google, and search for something."
    #   "Create a folder and move these files into it."
    #   "Open Notes and click New Note."
    is_open_browser_search = bool(re.match(r"^open\s+(?:the\s+)?browser\s+and\s+search\s+", lower))
    has_subsequent_action = bool(re.search(r"\b(?:and|then)\s+(?:play|select|click|open|watch)\b|(?:\b(?:second|first|third)\s+video\b)", lower))
    is_single_website_search = (
        bool(re.search(
            r"^(?:open|go\s+to)\s+(?:the\s+browser\s+and\s+)?(?:the\s+)?(?:youtube|google|wikipedia|github|amazon|reddit|duckduckgo|bing)\s+and\s+(?:search|find|look\s+up)\b",
            lower
        ))
        and not has_subsequent_action
    )
    has_seq_conjunction = bool(re.search(r"\b(?:then|and\s+then|after\s+that|next|finally|and\s+return\s+to|and\s+switch\s+back\s+to|;\s*)\b", lower))
    has_clause_commas = bool(re.search(r",\s*(?:visit|open|search|find|change|set|adjust|create|make|move|read|write|tell|return|switch|play|select|watch)\b", lower))
    has_and_action_verb = bool(re.search(r"\s+and\s+(?:change|set|adjust|visit|navigate|go\s+to|create|make|move|copy|read|write|tell|summarize|return|switch|download|save|open\s+it|click|double\s+click|right\s+click|press|tap|play|select|watch)\b", lower))
    has_find_and_open = bool(re.search(r"\b(?:find|locate)\b.*\band\s+(?:open|read|tell|view|show)\b", lower))
    has_create_and_move = bool(re.search(r"\b(?:create|make)\b.*\band\s+(?:move|put|copy|save)\b", lower))
    has_notes_chain = ("notes" in lower and any(w in lower for w in ["write", "save", "tasks", "create", "note"])) and any(w in lower for w in ["open", "search", "find", "summarize", "read", "camera", "picture", "photo", "tell me"])
    has_summarize_chain = any(w in lower for w in ["summarize", "main points", "collect the main"]) and any(w in lower for w in ["open", "search", "find", "pdf", "read", "inspect", "google", "youtube"])
    has_read_and_tell = bool(re.search(r"\bread\s+(?:it|this|the\s+pdf|my\s+pdf|its\s+contents)\s+and\s+(?:tell|summarize|explain)\b", lower))
    has_find_pdf_chain = ("find" in lower or "open" in lower) and "pdf" in lower and any(w in lower for w in ["read", "tell", "summarize", "contents"])

    is_explicit_file_search = any(w in lower for w in ["file named", "search my mac", "on my mac", "on my computer", "search for the file"])
    is_multistep_request = (
        not is_explicit_file_search and not is_open_browser_search and not is_single_website_search and (
            has_seq_conjunction or has_clause_commas or has_and_action_verb or
            has_find_and_open or has_create_and_move or has_notes_chain or
            has_summarize_chain or has_read_and_tell or has_find_pdf_chain or has_camera_multistep
        )
    )

    if is_multistep_request:
        return IntentResult(
            intent=IntentType.MULTISTEP_TASK,
            query=raw,
            explanation=f"Multi-step task workflow: '{raw}'.",
        )

    # 4b. Mouse & Button Control Intents
    # Direct clicking on buttons, UI elements, landmarks, coordinates, and cursor gliding
    mouse_intent = parse_mouse_and_click_intent(raw, lower)
    if mouse_intent:
        return mouse_intent

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
    # Examples: "Open Calculator", "Open Notes", "Open Safari", "Open the browser", "Open Camera"
    NON_APP_TARGETS = {
        "it", "them", "this", "that", "the file", "the app", "the window",
        "the document", "the page", "the tab", "a folder", "the folder",
        "files", "something"
    }
    m_app = re.search(r"^(?:open|launch)\s+(?:the\s+)?([a-zA-Z0-9\s]+?)(?:\s+(?:and|then|to|with)\b|\.|\,|$|\n)", lower)
    if not m_app:
        m_app = re.search(r"^(?:open|launch)\s+(?:the\s+)?([a-zA-Z0-9\s]+)$", lower)
    if m_app:
        candidate_app = m_app.group(1).strip()
        if candidate_app.lower() not in NON_APP_TARGETS:
            if candidate_app in ["camera", "webcam", "photo booth"]:
                return IntentResult(
                    intent=IntentType.OPEN_APPLICATION,
                    target_app="Photo Booth",
                    target_bundle_id="com.apple.PhotoBooth",
                    explanation="Launching camera application (Photo Booth).",
                )
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
