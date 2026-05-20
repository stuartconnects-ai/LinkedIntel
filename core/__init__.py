# core/__init__.py
"""
Core functionality modules for LinkedIntel — LinkedIn Engagement Intelligence.
Forked from PacemakerX/LinkedIntel, hardened and extended.

Security hardening:
  - SSL cert validation enabled
  - Daily action limits enforced
  - Target audience (ICP) filtering added
  - Improved AI prompt quality (no generic comments)

New modules:
  - ReplyTracker: monitors posts you've commented on for new replies
  - ContactManager: persistent ICP contact database with priority scoring
"""

from .auth import LinkedInAuth
from .feed_scrapper import FeedScraper
from .ai_filter import AIFilter
from .action_engine import ActionEngine
from .connect import LinkedInConnect
from .messenger import LinkedInMessenger
from .reply_tracker import ReplyTracker
from .contact_manager import ContactManager
from .search_engine import SearchEngine

__all__ = [
    'LinkedInAuth',
    'FeedScraper',
    'AIFilter',
    'ActionEngine',
    'LinkedInConnect',
    'LinkedInMessenger',
    'ReplyTracker',
    'ContactManager',
    'SearchEngine',
]
