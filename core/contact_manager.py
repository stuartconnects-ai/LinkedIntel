"""
Contact Manager — Priority Engagement CRM for LinkedIn.

Maintains a persistent database of target audience contacts, tracks
engagement depth, and generates daily priority engagement lists.

Contact Tiers:
  Tier 1 (🔥 Hot):    Replied to your comment — conversation in progress
  Tier 2 (🟡 Warm):   Engaged multiple times, rapport building
  Tier 3 (🟢 New):    High-ICP match, not yet engaged
  Tier 4 (⚪ Cold):   Low engagement or dormant (skip till active)

Priority Score Formula:
  base_icp_score (0-100)
  + (interactions * 15)  — each comment/reply exchange
  + (replies_received * 30)  — they replied to you = strong signal
  + recency_bonus: posted within 24h=20, 72h=10, 7d=5
  - days_since_last_contact * 2  — decay over time
"""
import time
import json
import hashlib
from pathlib import Path
from datetime import datetime, timedelta

from config import (
    DATA_DIR,
    TARGET_KEYWORDS,
    EXCLUDE_KEYWORDS,
    MIN_TARGET_MATCH_SCORE,
)


class ContactManager:
    def __init__(self):
        self.contacts_path = Path(DATA_DIR) / "contacts.json"
        Path(DATA_DIR).mkdir(parents=True, exist_ok=True)
        self.contacts = self._load()

    def _load(self):
        """Load contacts database."""
        if self.contacts_path.exists():
            try:
                with open(self.contacts_path, 'r') as f:
                    return json.load(f)
            except (json.JSONDecodeError, IOError):
                pass
        return {}

    def _save(self):
        """Save contacts database."""
        with open(self.contacts_path, 'w') as f:
            json.dump(self.contacts, f, indent=2, default=str)

    # ── Contact ID Generation ──────────────────────────────────────

    def _make_contact_id(self, author_name, profile_url):
        """Generate a stable contact ID from name + profile URL."""
        raw = f"{author_name}:{profile_url}"
        return hashlib.sha256(raw.encode()).hexdigest()[:16]

    def _extract_profile_id(self, profile_url):
        """Extract LinkedIn profile ID from URL."""
        if not profile_url:
            return ""
        try:
            if "linkedin.com/in/" in profile_url:
                return profile_url.split("/in/")[1].split("/")[0].split("?")[0]
        except Exception:
            pass
        return ""

    # ── ICP Scoring ────────────────────────────────────────────────

    def score_icp(self, author_name, author_headline, post_text=""):
        """
        Score a contact against the Ideal Customer Profile.
        Returns (score, matched_keywords, excluded).
        """
        combined = f"{author_name} {author_headline} {post_text}".lower()
        score = 0
        matched = []

        # Check exclusions first (instant rejection)
        for kw in EXCLUDE_KEYWORDS:
            if kw.lower() in combined:
                return 0, [], [kw]

        # Score inclusions
        for kw in TARGET_KEYWORDS:
            if kw.lower() in combined:
                score += 25
                matched.append(kw)

        score = min(score, 50)

        # Seniority signals
        seniority = ["years", "experience", "scale", "team of", "revenue",
                     "led", "built", "founded", "grew", "managing", "director"]
        for signal in seniority:
            if signal in combined:
                score += 10
                if "seniority" not in matched:
                    matched.append("seniority")
                break

        # Business content signals (from posts)
        business = ["revenue", "team", "scale", "growth", "hire", "hiring",
                    "leadership", "strategy", "business", "company", "startup",
                    "client", "customer", "profit", "margin", "acquisition"]
        biz_count = sum(1 for s in business if s in combined)
        score += min(biz_count * 5, 40)

        if biz_count > 2:
            matched.append("business_content")

        return min(score, 100), matched, []

    # ── Contact CRUD ───────────────────────────────────────────────

    def get_or_create_contact(self, author_name, author_headline="", profile_url=""):
        """Get existing contact or create a new entry."""
        contact_id = self._make_contact_id(author_name, profile_url)

        if contact_id in self.contacts:
            return self.contacts[contact_id]

        icp_score, matched_kw, excluded = self.score_icp(author_name, author_headline)

        if icp_score < MIN_TARGET_MATCH_SCORE:
            return None  # Not target audience

        contact = {
            "contact_id": contact_id,
            "name": author_name,
            "headline": author_headline,
            "profile_url": profile_url,
            "profile_id": self._extract_profile_id(profile_url),
            "icp_score": icp_score,
            "icp_matched": matched_kw,

            # Engagement tracking
            "interactions": 0,           # Total times engaged
            "comments_made": [],          # [{post_id, timestamp, comment_text}]
            "replies_received": [],       # [{post_id, reply_text, timestamp, status}]
            "first_seen": time.time(),
            "last_seen_in_feed": time.time(),
            "last_engaged": None,        # Last time we commented on their post
            "last_posted": None,         # Last time they posted (from feed)

            # Priority
            "tier": "new",
            "priority_score": icp_score,
            "tags": [],
            "notes": ""
        }

        self.contacts[contact_id] = contact
        return contact

    def update_contact(self, contact):
        """Update contact data."""
        contact_id = contact.get("contact_id")
        if contact_id:
            self.contacts[contact_id] = contact

    def get_contact(self, contact_id):
        """Get contact by ID."""
        return self.contacts.get(contact_id)

    # ── Engagement Tracking ────────────────────────────────────────

    def record_engagement(self, author_name, profile_url, author_headline,
                          post_id, post_url, comment_text, reply_data=None):
        """Record that we engaged with this contact's post."""
        contact = self.get_or_create_contact(author_name, author_headline, profile_url)
        if not contact:
            return None

        contact["interactions"] += 1
        contact["last_engaged"] = time.time()
        contact["comments_made"].append({
            "post_id": post_id,
            "post_url": post_url,
            "timestamp": time.time(),
            "comment_text": comment_text[:200]
        })

        # Cap stored comments to last 50
        if len(contact["comments_made"]) > 50:
            contact["comments_made"] = contact["comments_made"][-50:]

        self._recalculate_tier(contact)
        self._save()
        return contact

    def record_reply_received(self, author_name, profile_url, author_headline,
                              post_id, post_url, reply_text, reply_timestamp=None):
        """Record that this contact replied to our comment."""
        contact = self.get_or_create_contact(author_name, author_headline, profile_url)
        if not contact:
            return None

        contact["replies_received"].append({
            "post_id": post_id,
            "post_url": post_url,
            "reply_text": reply_text[:300],
            "timestamp": reply_timestamp or time.time(),
            "status": "new"
        })
        contact["interactions"] += 1

        self._recalculate_tier(contact)
        self._save()
        return contact

    def mark_reply_handled(self, contact_id, reply_index):
        """Mark a reply as handled."""
        contact = self.contacts.get(contact_id)
        if contact and reply_index < len(contact.get("replies_received", [])):
            contact["replies_received"][reply_index]["status"] = "handled"
            self._save()

    def record_seen_in_feed(self, author_name, profile_url, author_headline, post_timestamp=None):
        """Record that this contact appeared in the feed."""
        contact = self.get_or_create_contact(author_name, author_headline, profile_url)
        if not contact:
            return None

        contact["last_seen_in_feed"] = time.time()
        if post_timestamp:
            contact["last_posted"] = post_timestamp
        self._save()
        return contact

    # ── Tier & Priority Calculation ────────────────────────────────

    def _recalculate_tier(self, contact):
        """Recalculate contact tier based on engagement depth."""
        unread_replies = sum(
            1 for r in contact.get("replies_received", [])
            if r.get("status") == "new"
        )

        interactions = contact.get("interactions", 0)

        if unread_replies > 0:
            contact["tier"] = "hot"       # 🔥 They replied — requires attention
        elif interactions >= 3:
            contact["tier"] = "warm"      # 🟡 Building rapport
        elif interactions >= 1:
            contact["tier"] = "new"       # 🟢 First contact made
        else:
            contact["tier"] = "cold"      # ⚪ Not yet engaged

        # Priority score
        score = contact.get("icp_score", 0)
        score += interactions * 15
        score += sum(
            1 for r in contact.get("replies_received", [])
            if r.get("status") == "new"
        ) * 30

        # Recency bonus
        last_posted = contact.get("last_posted")
        if last_posted:
            hours_ago = (time.time() - last_posted) / 3600
            if hours_ago < 24:
                score += 20
            elif hours_ago < 72:
                score += 10
            elif hours_ago < 168:
                score += 5

        # Decay: lose 2 points per day since last engaged
        last_engaged = contact.get("last_engaged")
        if last_engaged:
            days_since = (time.time() - last_engaged) / 86400
            score -= int(days_since * 2)

        contact["priority_score"] = max(0, score)

    def recalculate_all(self):
        """Recalculate tiers and scores for all contacts."""
        for contact in self.contacts.values():
            self._recalculate_tier(contact)
        self._save()

    # ── Priority List Generation ───────────────────────────────────

    def get_priority_list(self, max_contacts=20, include_cold=False):
        """
        Generate today's priority engagement list.

        Returns list sorted by priority_score descending, grouped by tier.
        """
        tiers = {
            "hot": [],
            "warm": [],
            "new": [],
            "cold": []
        }

        for contact in self.contacts.values():
            tier = contact.get("tier", "cold")
            if tier == "cold" and not include_cold:
                continue
            tiers[tier].append(contact)

        # Sort each tier by priority_score
        for tier in tiers:
            tiers[tier].sort(key=lambda c: c.get("priority_score", 0), reverse=True)

        # Merge: hot → warm → new → cold, capped at max_contacts
        result = []
        for tier_key in ["hot", "warm", "new", "cold"]:
            result.extend(tiers[tier_key][:max_contacts - len(result)])
            if len(result) >= max_contacts:
                break

        return result[:max_contacts]

    def get_contacts_by_tier(self, tier):
        """Get all contacts in a specific tier."""
        return sorted(
            [c for c in self.contacts.values() if c.get("tier") == tier],
            key=lambda c: c.get("priority_score", 0),
            reverse=True
        )

    def get_contact_history(self, contact_id):
        """Get full engagement history for a contact."""
        contact = self.contacts.get(contact_id)
        if not contact:
            return None

        history = {
            "name": contact.get("name"),
            "headline": contact.get("headline"),
            "tier": contact.get("tier"),
            "icp_score": contact.get("icp_score"),
            "priority_score": contact.get("priority_score"),
            "interactions": contact.get("interactions"),
            "comments_made": contact.get("comments_made", []),
            "replies_received": contact.get("replies_received", []),
            "tags": contact.get("tags", []),
            "notes": contact.get("notes", "")
        }
        return history

    def add_tags(self, contact_id, tags):
        """Add tags to a contact."""
        contact = self.contacts.get(contact_id)
        if contact:
            existing = set(contact.get("tags", []))
            existing.update(tags)
            contact["tags"] = list(existing)
            self._save()

    def add_note(self, contact_id, note):
        """Add a note to a contact."""
        contact = self.contacts.get(contact_id)
        if contact:
            timestamp = datetime.now().isoformat()
            if "notes" not in contact or not contact["notes"]:
                contact["notes"] = ""
            contact["notes"] += f"\n[{timestamp}] {note}"
            self._save()

    # ── Stats & Reporting ──────────────────────────────────────────

    def get_stats(self):
        """Get contact database statistics."""
        tiers = {"hot": 0, "warm": 0, "new": 0, "cold": 0}
        total = 0
        total_interactions = 0
        total_replies = 0

        for contact in self.contacts.values():
            total += 1
            tier = contact.get("tier", "cold")
            tiers[tier] = tiers.get(tier, 0) + 1
            total_interactions += contact.get("interactions", 0)
            total_replies += len(contact.get("replies_received", []))

        return {
            "total_contacts": total,
            "by_tier": tiers,
            "total_interactions": total_interactions,
            "total_replies_received": total_replies,
            "database_size_kb": round(self.contacts_path.stat().st_size / 1024, 1) if self.contacts_path.exists() else 0
        }

    def print_priority_list(self, max_contacts=15):
        """Print a human-readable priority engagement list."""
        contacts = self.get_priority_list(max_contacts)
        stats = self.get_stats()

        print("\n" + "=" * 60)
        print("📋 DAILY PRIORITY ENGAGEMENT LIST")
        print("=" * 60)
        print(f"Database: {stats['total_contacts']} contacts | "
              f"🔥{stats['by_tier']['hot']} 🟡{stats['by_tier']['warm']} "
              f"🟢{stats['by_tier']['new']} ⚪{stats['by_tier']['cold']}")
        print("-" * 60)

        if not contacts:
            print("\n   No contacts yet. Run feed engagement to build your list.")
            return

        tier_emoji = {"hot": "🔥", "warm": "🟡", "new": "🟢", "cold": "⚪"}
        current_tier = None

        for i, contact in enumerate(contacts, 1):
            tier = contact.get("tier", "cold")

            if tier != current_tier:
                current_tier = tier
                tier_label = {
                    "hot": "🔥 TIER 1 — Replied to you (respond TODAY)",
                    "warm": "🟡 TIER 2 — Building rapport (engage this week)",
                    "new": "🟢 TIER 3 — New high-ICP matches (start engaging)",
                    "cold": "⚪ TIER 4 — Dormant (skip for now)"
                }
                print(f"\n{tier_label.get(tier, tier)}")

            emoji = tier_emoji.get(tier, "  ")
            name = contact.get("name", "Unknown")
            headline = contact.get("headline", "")[:60]
            score = contact.get("priority_score", 0)
            interactions = contact.get("interactions", 0)
            unread_replies = sum(
                1 for r in contact.get("replies_received", [])
                if r.get("status") == "new"
            )

            reply_flag = f" ⬅️ {unread_replies} new reply" if unread_replies > 0 else ""
            interact_flag = f" [{interactions}x engaged]" if interactions > 0 else ""

            print(f"  #{i:2d} {emoji} {name} ({score}pts)  ")
            print(f"       {headline}{interact_flag}{reply_flag}")

        print("\n" + "-" * 60)
        print("Run: python main.py --mode feed    → engage with these contacts")
        print("Run: python main.py --mode replies → check for new replies")
        print("=" * 60 + "\n")

    def print_contact_detail(self, contact_id):
        """Print detailed history for a specific contact."""
        contact = self.contacts.get(contact_id)
        if not contact:
            print(f"Contact {contact_id} not found.")
            return

        print(f"\n{'='*50}")
        print(f"👤 {contact.get('name', 'Unknown')}")
        print(f"   {contact.get('headline', '')}")
        print(f"   Profile: {contact.get('profile_url', 'N/A')}")
        print(f"   Tier: {contact.get('tier', 'cold')} | "
              f"ICP: {contact.get('icp_score', 0)} | "
              f"Priority: {contact.get('priority_score', 0)}")
        print(f"   Interactions: {contact.get('interactions', 0)}")
        print(f"{'='*50}")

        comments = contact.get("comments_made", [])
        if comments:
            print(f"\n💬 Comments made ({len(comments)}):")
            for c in comments[-10:]:  # Last 10
                ts = datetime.fromtimestamp(c.get("timestamp", 0)).strftime("%d %b %Y")
                text = c.get("comment_text", "")[:120]
                print(f"   [{ts}] {text}")

        replies = contact.get("replies_received", [])
        if replies:
            print(f"\n↩️  Replies received ({len(replies)}):")
            for r in replies:
                status = "✅" if r.get("status") == "handled" else "🆕"
                text = r.get("reply_text", "")[:150]
                print(f"   {status} {text}")

        tags = contact.get("tags", [])
        if tags:
            print(f"\n🏷️  Tags: {', '.join(tags)}")

        notes = contact.get("notes", "")
        if notes:
            print(f"\n📝 Notes:{notes}")
        print()
