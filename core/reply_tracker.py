"""
Reply Tracking Module — monitors posts you've commented on for new replies.
Enables conversation management by detecting when someone responds to your comments.
"""
import time
import json
import re
from pathlib import Path
from datetime import datetime
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import NoSuchElementException, TimeoutException

from config import (
    DATA_DIR,
    MAX_REPLY_CHECK_POSTS,
    REPLY_CHECK_INTERVAL_HOURS,
    MIN_ACTION_DELAY,
    MAX_ACTION_DELAY
)


class ReplyTracker:
    """
    Monitors LinkedIn posts for replies to your comments.

    Workflow:
    1. Load history.json to find posts you've commented on
    2. Visit each post URL via LinkedIn
    3. Find your comment in the comments section
    4. Check for nested replies under your comment
    5. Compare against replies.json to identify NEW replies
    6. Flag new replies for your review
    """

    def __init__(self, linkedin_name=None):
        self.history_path = Path(DATA_DIR) / "history.json"
        self.replies_path = Path(DATA_DIR) / "replies.json"
        self.linkedin_name = linkedin_name  # Your display name on LinkedIn

        # Ensure data directory exists
        Path(DATA_DIR).mkdir(parents=True, exist_ok=True)

        self.history = self._load_json(self.history_path, {"likes": {}, "comments": {}, "connections": {}, "messages": {}})
        self.replies_state = self._load_json(self.replies_path, {})

    def _load_json(self, path, default):
        """Load JSON file, return default if not found or corrupted."""
        if path.exists():
            try:
                with open(path, 'r') as f:
                    return json.load(f)
            except (json.JSONDecodeError, IOError):
                return default
        return default

    def _save_json(self, path, data):
        """Save data to JSON file."""
        with open(path, 'w') as f:
            json.dump(data, f, indent=2, default=str)

    def get_commented_posts(self, max_posts=None):
        """
        Get list of post IDs and URLs we've commented on, sorted by recency.
        Returns list of {post_id, timestamp, comment_text, post_url}.
        """
        max_posts = max_posts or MAX_REPLY_CHECK_POSTS

        posts = []
        for post_id, data in self.history.get("comments", {}).items():
            posts.append({
                "post_id": post_id,
                "timestamp": data.get("timestamp", 0),
                "comment_text": data.get("details", {}).get("text", ""),
                "post_url": data.get("details", {}).get("post_url", "")
            })

        # Sort by most recent first
        posts.sort(key=lambda x: x["timestamp"], reverse=True)
        return posts[:max_posts]

    def check_for_replies(self, driver, max_posts=None, dry_run=False):
        """
        Visit posts we've commented on and check for new replies.

        Args:
            driver: Selenium WebDriver (must already be logged into LinkedIn)
            max_posts: Max number of posts to check
            dry_run: If True, find replies but don't update state

        Returns:
            list of new replies: [{reply_id, post_id, post_url, my_comment,
                                   author_name, author_headline, reply_text, timestamp}]
        """
        posts_to_check = self.get_commented_posts(max_posts)
        new_replies = []

        if not posts_to_check:
            print("   No posts with comments found in history.")
            return new_replies

        print(f"   Checking {len(posts_to_check)} posts for replies...")

        for i, post in enumerate(posts_to_check):
            post_id = post["post_id"]
            post_url = post.get("post_url", "")

            # Skip if checked recently
            last_check = self.replies_state.get(post_id, {}).get("last_checked", 0)
            hours_since_check = (time.time() - last_check) / 3600
            if hours_since_check < REPLY_CHECK_INTERVAL_HOURS and last_check > 0:
                print(f"   [{i+1}/{len(posts_to_check)}] Post {post_id[:12]}... ⏭️  checked {hours_since_check:.1f}h ago")
                continue

            # Skip if no post URL
            if not post_url:
                print(f"   [{i+1}/{len(posts_to_check)}] Post {post_id[:12]}... ⏭️  no URL available")
                continue

            print(f"   [{i+1}/{len(posts_to_check)}] Checking post {post_id[:12]}... ", end="", flush=True)

            try:
                # Navigate to the post
                driver.get(post_url)
                time.sleep(3)  # Let comments load

                # Find replies to our comments
                post_replies = self._find_replies_on_post(driver, post)

                if post_replies:
                    print(f"✅ {len(post_replies)} new replies")
                    new_replies.extend(post_replies)
                else:
                    print("no new replies")

            except Exception as e:
                print(f"⚠️  error: {str(e)[:80]}")

            # Update last checked timestamp
            if not dry_run:
                if post_id not in self.replies_state:
                    self.replies_state[post_id] = {}
                self.replies_state[post_id]["last_checked"] = time.time()

            # Random delay between post checks
            if i < len(posts_to_check) - 1:
                time.sleep(1.5 + time.time() % 1.5)

        # Save updated state
        if not dry_run:
            self._save_json(self.replies_path, self.replies_state)

        return new_replies

    def _find_replies_on_post(self, driver, post_data):
        """
        Find replies to our comment on a specific post page.

        Strategy:
        1. Scroll to comments section
        2. Look for our comment by searching for our name
        3. Check for nested reply elements under our comment
        4. Extract reply details
        """
        post_id = post_data["post_id"]
        my_comment_text = post_data.get("comment_text", "")
        post_url = driver.current_url
        new_replies = []

        try:
            # Scroll down to load comments
            driver.execute_script("window.scrollBy(0, 600);")
            time.sleep(1.5)

            # Find all comment containers
            comment_sections = driver.find_elements(
                By.CSS_SELECTOR, "article.comments-comment-item, div.comments-comment-entity"
            )

            if not comment_sections:
                # Try alternative selectors that LinkedIn sometimes uses
                comment_sections = driver.find_elements(
                    By.CSS_SELECTOR, "[data-finite-scroll-hotkey-item] article"
                )

            if not comment_sections:
                return []

            # Get our LinkedIn name from profile if not set
            if not self.linkedin_name:
                self.linkedin_name = self._get_own_name(driver)

            # Find our comment
            for comment_section in comment_sections:
                try:
                    # Check if this comment is ours (by name match)
                    commenter_elem = comment_section.find_element(
                        By.CSS_SELECTOR, ".comments-comment-meta__actor, .feed-shared-actor__name"
                    )
                    commenter_name = commenter_elem.text.strip()

                    if not self._is_my_comment(commenter_name, my_comment_text, comment_section):
                        continue

                    # Found our comment — now look for replies
                    reply_elements = comment_section.find_elements(
                        By.CSS_SELECTOR, ".comments-reply-item, article.comments-comment-item"
                    )

                    for reply_elem in reply_elements:
                        try:
                            reply_data = self._extract_reply(driver, reply_elem, post_id, post_url, my_comment_text)
                            if reply_data and not self._is_reply_known(reply_data["reply_id"]):
                                new_replies.append(reply_data)
                        except Exception:
                            continue

                    # Also check for "Show replies" button
                    try:
                        show_replies_btn = comment_section.find_element(
                            By.CSS_SELECTOR, "button.comments-replies-pagination__show-more"
                        )
                        driver.execute_script("arguments[0].click();", show_replies_btn)
                        time.sleep(1.5)

                        # Re-check for newly loaded replies
                        reply_elements = comment_section.find_elements(
                            By.CSS_SELECTOR, ".comments-reply-item, article.comments-comment-item"
                        )
                        for reply_elem in reply_elements:
                            try:
                                reply_data = self._extract_reply(driver, reply_elem, post_id, post_url, my_comment_text)
                                if reply_data and not self._is_reply_known(reply_data["reply_id"]):
                                    new_replies.append(reply_data)
                            except Exception:
                                continue
                    except NoSuchElementException:
                        pass

                    break  # Found our comment, no need to check others

                except NoSuchElementException:
                    continue

        except Exception as e:
            print(f"(reply scan: {str(e)[:60]})")

        return new_replies

    def _is_my_comment(self, commenter_name, my_comment_text, comment_element):
        """Determine if a comment is ours — by name match or text match."""
        # Name match
        if self.linkedin_name and self.linkedin_name.lower() in commenter_name.lower():
            return True

        # Comment text match (fallback)
        if my_comment_text:
            try:
                comment_body = comment_element.find_element(
                    By.CSS_SELECTOR, ".comments-comment-item__main-content, .feed-shared-text"
                )
                body_text = comment_body.text.strip()
                # Check if the first 60 chars of our comment appears in this comment
                if my_comment_text[:60].strip() in body_text:
                    return True
            except NoSuchElementException:
                pass

        return False

    def _extract_reply(self, driver, reply_element, post_id, post_url, my_comment_text):
        """Extract reply data from a reply element."""
        try:
            # Get reply author
            try:
                author_elem = reply_element.find_element(
                    By.CSS_SELECTOR, ".comments-comment-meta__actor, .feed-shared-actor__name"
                )
                author_name = author_elem.text.strip()
            except NoSuchElementException:
                author_name = "Unknown"

            # Get reply author headline
            try:
                headline_elem = reply_element.find_element(
                    By.CSS_SELECTOR, ".comments-comment-meta__headline, .feed-shared-actor__subtitle"
                )
                author_headline = headline_elem.text.strip()
            except NoSuchElementException:
                author_headline = ""

            # Get reply text
            try:
                text_elem = reply_element.find_element(
                    By.CSS_SELECTOR, ".comments-comment-item__main-content, .feed-shared-text"
                )
                reply_text = text_elem.text.strip()
            except NoSuchElementException:
                reply_text = ""

            # Get reply timestamp
            try:
                time_elem = reply_element.find_element(By.CSS_SELECTOR, "time")
                reply_timestamp = time_elem.get_attribute("datetime") or ""
            except NoSuchElementException:
                reply_timestamp = datetime.now().isoformat()

            # Generate unique reply ID
            reply_id = f"{post_id}:reply:{author_name}:{hash(reply_text[:50])}"

            return {
                "reply_id": reply_id,
                "post_id": post_id,
                "post_url": post_url,
                "my_comment": my_comment_text[:200],
                "author_name": author_name,
                "author_headline": author_headline,
                "reply_text": reply_text,
                "timestamp": reply_timestamp,
                "discovered_at": time.time(),
                "status": "new"
            }

        except Exception as e:
            print(f"(extract reply: {e})")
            return None

    def _get_own_name(self, driver):
        """Extract your LinkedIn display name from the page."""
        try:
            # Try the profile dropdown trigger
            name_elem = driver.find_element(
                By.CSS_SELECTOR, ".global-nav__me-photo, .profile-rail-card__actor-link"
            )
            name = name_elem.get_attribute("alt") or name_elem.get_attribute("title") or ""
            return name.strip()
        except NoSuchElementException:
            return ""

    def _is_reply_known(self, reply_id):
        """Check if a reply has already been recorded."""
        for post_id, data in self.replies_state.items():
            known = data.get("replies", {})
            if reply_id in known:
                return True
        return False

    def mark_replies_seen(self, reply_ids):
        """Mark replies as 'seen' so they won't appear as new on next check."""
        for reply_id in reply_ids:
            # Extract post_id from reply_id
            post_id = reply_id.split(":reply:")[0]
            if post_id not in self.replies_state:
                self.replies_state[post_id] = {"replies": {}}

            if reply_id not in self.replies_state[post_id].get("replies", {}):
                if "replies" not in self.replies_state[post_id]:
                    self.replies_state[post_id]["replies"] = {}

            self.replies_state[post_id]["replies"][reply_id] = {
                "status": "seen",
                "seen_at": time.time()
            }

        self._save_json(self.replies_path, self.replies_state)

    def get_all_unread_replies(self):
        """
        Get ALL unread replies across all posts (for dashboard/summary use).
        Returns list of reply dicts with status='new'.
        """
        unread = []
        for post_id, data in self.replies_state.items():
            for reply_id, reply_data in data.get("replies", {}).items():
                if reply_data.get("status") == "new":
                    unread.append({
                        "reply_id": reply_id,
                        "post_id": post_id,
                        "status": "new",
                        **reply_data
                    })
        return sorted(unread, key=lambda x: x.get("discovered_at", 0), reverse=True)

    def print_summary(self):
        """Print a summary of reply tracking state."""
        total_posts = len(self.history.get("comments", {}))
        total_replies = sum(
            len(data.get("replies", {}))
            for data in self.replies_state.values()
        )
        unread = len(self.get_all_unread_replies())

        print(f"📊 Reply Tracker Summary:")
        print(f"   Posts commented on: {total_posts}")
        print(f"   Total replies received: {total_replies}")
        print(f"   Unread replies: {unread}")
