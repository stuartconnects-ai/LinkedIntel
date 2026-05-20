# core/action_engine.py
import time
import random
import json
from pathlib import Path
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import NoSuchElementException

from config import (
    DATA_DIR,
    MIN_ACTION_DELAY,
    MAX_ACTION_DELAY,
    MAX_LIKES_PER_DAY,
    MAX_COMMENTS_PER_DAY,
)


class ActionEngine:
    def __init__(self):
        self.history_path = Path(DATA_DIR) / "history.json"
        self.action_history = self._load_history()

    def _load_history(self):
        if self.history_path.exists():
            try:
                with open(self.history_path, 'r') as f:
                    return json.load(f)
            except (json.JSONDecodeError, IOError):
                return {"likes": {}, "comments": {}, "connections": {}, "messages": {}}
        else:
            Path(DATA_DIR).mkdir(parents=True, exist_ok=True)
            return {"likes": {}, "comments": {}, "connections": {}, "messages": {}}

    def _save_history(self):
        with open(self.history_path, 'w') as f:
            json.dump(self.action_history, f, indent=2, default=str)

    def has_interacted_with_post(self, post_id, action_type):
        return post_id in self.action_history.get(action_type, {})

    def record_interaction(self, post_id, action_type, details=None):
        if action_type not in self.action_history:
            self.action_history[action_type] = {}

        self.action_history[action_type][post_id] = {
            "timestamp": time.time(),
            "details": details or {}
        }

        self._save_history()

    def get_daily_count(self, action_type):
        """Count actions of given type performed in the last 24 hours."""
        today_start = time.time() - 86400
        count = 0
        for post_id, data in self.action_history.get(action_type, {}).items():
            if data.get("timestamp", 0) > today_start:
                count += 1
        return count

    def is_within_daily_limit(self, action_type):
        """Check if we're still within the daily limit for this action type."""
        daily_count = self.get_daily_count(action_type)
        limits = {
            "likes": MAX_LIKES_PER_DAY,
            "comments": MAX_COMMENTS_PER_DAY,
        }
        limit = limits.get(action_type, 10)
        return daily_count < limit

    def perform_actions(self, driver, post_data, analysis_result):
        post_id = post_data.get("post_id", "").split(":")[-1]
        post_element = post_data.get("post_element")
        post_url = post_data.get("post_url", "")

        results = {
            "liked": False,
            "commented": False,
            "comment_text": "",
            "errors": []
        }

        if not post_element:
            results["errors"].append("Post element not found")
            return results

        try:
            self._reposition_post(driver, post_element)

            # LIKE — with daily limit check
            should_like = bool(analysis_result.get("should_like", False))
            if should_like and not self.has_interacted_with_post(post_id, "likes"):
                if self.is_within_daily_limit("likes"):
                    print(f"Analysis recommends liking post: {post_id}")
                    if self.like_post(driver, post_element):
                        results["liked"] = True
                        self.record_interaction(post_id, "likes", {"post_url": post_url})
                        self._random_delay(1, 2)
                else:
                    print(f"Skipping like (daily limit): {post_id}")
            else:
                print(f"Skipping like for post: {post_id}, should_like={should_like}")

            # COMMENT — with daily limit check
            comment_text = analysis_result.get("comment_text", "")
            should_comment = bool(analysis_result.get("should_comment", False))

            if not should_comment or comment_text == "[N/A]" or not comment_text:
                print(f"Skipping comment for post: {post_id}, should_comment={should_comment}")
            elif self.has_interacted_with_post(post_id, "comments"):
                print(f"Already commented on post: {post_id}")
            elif not self.is_within_daily_limit("comments"):
                print(f"Skipping comment (daily limit): {post_id}")
            else:
                print(f"Analysis recommends commenting on post: {post_id}")
                if self.comment_on_post(driver, post_element, comment_text):
                    results["commented"] = True
                    results["comment_text"] = comment_text
                    self.record_interaction(post_id, "comments", {
                        "text": comment_text,
                        "post_url": post_url
                    })

            # Scroll
            driver.execute_script("window.scrollBy(0, 400);")
            self._random_delay(1, 2)

        except Exception as e:
            error_msg = f"Error performing actions: {str(e)}"
            print(error_msg)
            results["errors"].append(error_msg)

        return results

    def like_post(self, driver, post_element):
        try:
            try:
                social_bar = post_element.find_element(
                    By.XPATH, ".//div[contains(@class, 'social-actions') or contains(@class, 'feed-shared-social-actions')]"
                )
            except NoSuchElementException:
                social_bar = post_element

            like_buttons = social_bar.find_elements(
                By.XPATH, ".//button[contains(@aria-label, 'Like') or contains(@aria-label, 'like')]"
            )

            if not like_buttons:
                return False

            for btn in like_buttons:
                try:
                    aria_label = btn.get_attribute("aria-label") or ""
                    is_pressed = btn.get_attribute("aria-pressed")

                    if ("Like" in aria_label or "like" in aria_label.lower()) and is_pressed != "true":
                        driver.execute_script("arguments[0].click();", btn)
                        print("✅ Liked post successfully")
                        self._random_delay()
                        return True
                except Exception:
                    continue

            return False

        except Exception as e:
            print(f"Error in like_post: {e}")
            return False

    def comment_on_post(self, driver, post_element, comment_text):
        try:
            # Click comment button
            comment_button = post_element.find_element(
                By.CSS_SELECTOR, "button.comment-button, button[data-control-name='comment']")
            driver.execute_script("arguments[0].scrollIntoView(true);", comment_button)
            self._random_delay(0.3, 0.6)
            driver.execute_script("arguments[0].click();", comment_button)

            self._random_delay(1, 1.5)

            # Find the comment editor
            comment_field = WebDriverWait(post_element, 10).until(
                EC.visibility_of_element_located((By.CSS_SELECTOR, "div.ql-editor"))
            )

            # Paste comment as a block (faster, less bot-like than char-by-char)
            driver.execute_script(
                "arguments[0].textContent = arguments[1];", comment_field, comment_text
            )
            comment_field.click()
            self._random_delay(1, 2)

            # Submit
            try:
                post_button = post_element.find_element(
                    By.CSS_SELECTOR, "button.comments-comment-box__submit-button--cr"
                )
            except NoSuchElementException:
                return False

            driver.execute_script("arguments[0].scrollIntoView(true);", post_button)
            self._random_delay(0.3, 0.6)
            driver.execute_script("arguments[0].click();", post_button)

            self._random_delay(2, 3)
            print(f"✅ Posted comment: {comment_text[:60]}...")
            return True

        except Exception as e:
            print(f"❌ Error commenting on post: {e}")
            return False

    def _reposition_post(self, driver, post_element):
        try:
            driver.execute_script("""
                arguments[0].scrollIntoView({behavior: 'smooth', block: 'center'});
                window.scrollBy(0, -150);
            """, post_element)
            self._random_delay(0.5, 1.5)
        except Exception as e:
            print(f"Error repositioning post: {e}")

    def _random_delay(self, min_delay=None, max_delay=None):
        min_delay = min_delay or MIN_ACTION_DELAY
        max_delay = max_delay or MAX_ACTION_DELAY
        time.sleep(random.uniform(min_delay, max_delay))
