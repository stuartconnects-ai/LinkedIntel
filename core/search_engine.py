"""
LinkedIn Search Engine — find target audience posts and people by keyword.

Supports:
  --search "leadership burnout"     Search posts by keyword
  --search "founder coach" --type people   Search people by keyword
  --search "scaling team" --engage          Search AND engage with results

Search URLs constructed with ICP filters applied automatically.
"""
import time
import random
from urllib.parse import quote
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, NoSuchElementException

from config import (
    MIN_SCROLL_DELAY,
    MAX_SCROLL_DELAY,
    TARGET_KEYWORDS,
    EXCLUDE_KEYWORDS,
)


class SearchEngine:
    """
    Search LinkedIn for posts or people matching your ICP.

    LinkedIn Search URL patterns:
      Posts:   https://www.linkedin.com/search/results/content/?keywords={query}
      People:  https://www.linkedin.com/search/results/people/?keywords={query}
    """

    POST_SEARCH_URL = "https://www.linkedin.com/search/results/content/"
    PEOPLE_SEARCH_URL = "https://www.linkedin.com/search/results/people/"

    def __init__(self):
        self.results = []

    def search_posts(self, driver, query, max_results=25, sort_by="relevance"):
        """
        Search LinkedIn for posts matching a keyword query.

        Args:
            driver: Selenium WebDriver (must be logged in)
            query: Search keywords (e.g. "leadership burnout")
            max_results: Max posts to return
            sort_by: "relevance" or "date"

        Returns:
            list of post dicts matching the search
        """
        url = f"{self.POST_SEARCH_URL}?keywords={quote(query)}&sortBy={'R' if sort_by == 'relevance' else 'DD'}"
        print(f"\n🔍 Searching posts: \"{query}\" ({sort_by})")
        print(f"   URL: {url}")

        driver.get(url)
        time.sleep(3)

        posts = []
        scroll_count = 0
        max_scrolls = 10

        while len(posts) < max_results and scroll_count < max_scrolls:
            # Find post results
            post_elements = driver.find_elements(
                By.CSS_SELECTOR, ".feed-shared-update-v2, .search-result__occluded-item"
            )

            for post_element in post_elements:
                try:
                    post_data = self._extract_post_from_search(driver, post_element)
                    if post_data and post_data.get("post_text", "").strip():
                        # Check if already collected
                        existing_ids = [p.get("post_id") for p in posts]
                        if post_data["post_id"] not in existing_ids:
                            posts.append(post_data)

                            if len(posts) >= max_results:
                                break
                except Exception as e:
                    continue

            # Scroll for more results
            if len(posts) < max_results:
                driver.execute_script("window.scrollBy(0, 800);")
                time.sleep(random.uniform(MIN_SCROLL_DELAY, MAX_SCROLL_DELAY))
                scroll_count += 1

        print(f"   ✅ Found {len(posts)} posts")
        self.results = posts
        return posts

    def search_people(self, driver, query, max_results=25):
        """
        Search LinkedIn for people matching a keyword query.
        Filters by 1st/2nd degree connections automatically.

        Returns list of profile dicts.
        """
        url = f"{self.PEOPLE_SEARCH_URL}?keywords={quote(query)}&network=[\"F\",\"S\"]"
        print(f"\n🔍 Searching people: \"{query}\"")
        print(f"   URL: {url}")

        driver.get(url)
        time.sleep(3)

        people = []
        scroll_count = 0
        max_scrolls = 8

        while len(people) < max_results and scroll_count < max_scrolls:
            person_cards = driver.find_elements(
                By.CSS_SELECTOR, ".reusable-search__result-container"
            )

            for card in person_cards:
                try:
                    person_data = self._extract_person_from_search(card)
                    if person_data:
                        existing = [p.get("profile_id") for p in people]
                        if person_data["profile_id"] not in existing:
                            people.append(person_data)

                            if len(people) >= max_results:
                                break
                except Exception:
                    continue

            if len(people) < max_results:
                driver.execute_script("window.scrollBy(0, 800);")
                time.sleep(random.uniform(MIN_SCROLL_DELAY, MAX_SCROLL_DELAY))
                scroll_count += 1

        print(f"   ✅ Found {len(people)} people")
        return people

    def _extract_post_from_search(self, driver, post_element):
        """Extract post data from a search result element."""
        try:
            post_id = post_element.get_attribute("data-urn") or ""

            # Author
            author_name = "Unknown"
            author_link = ""
            author_headline = ""
            try:
                author_container = post_element.find_element(
                    By.CSS_SELECTOR, "a.update-components-actor__meta-link"
                )
                author_link = author_container.get_attribute("href").strip()
                try:
                    name_span = author_container.find_element(
                        By.CSS_SELECTOR, ".update-components-actor__title span span[aria-hidden='true']"
                    )
                    author_name = name_span.text.strip()
                except NoSuchElementException:
                    if "linkedin.com/in/" in author_link:
                        name_part = author_link.split("linkedin.com/in/")[1].split("?")[0]
                        author_name = name_part.replace("-", " ").title()

                try:
                    headline_elem = post_element.find_element(
                        By.CSS_SELECTOR, ".update-components-actor__description"
                    )
                    author_headline = headline_elem.text.strip()
                except NoSuchElementException:
                    pass
            except NoSuchElementException:
                pass

            # Post text
            post_text = ""
            try:
                text_elem = post_element.find_element(
                    By.CSS_SELECTOR, ".feed-shared-update-v2__description"
                )
                post_text = text_elem.text.strip()
            except NoSuchElementException:
                try:
                    text_elem = post_element.find_element(
                        By.CSS_SELECTOR, ".feed-shared-text"
                    )
                    post_text = text_elem.text.strip()
                except NoSuchElementException:
                    pass

            # Post URL
            post_url = ""
            try:
                url_elem = post_element.find_element(
                    By.CSS_SELECTOR, ".feed-shared-update-v2__update-link-container a"
                )
                post_url = url_elem.get_attribute("href")
            except NoSuchElementException:
                if "activity" in post_id:
                    aid = post_id.split(":")[-1]
                    post_url = f"https://www.linkedin.com/feed/update/urn:li:activity:{aid}"

            return {
                "post_id": post_id,
                "author_name": author_name,
                "author_headline": author_headline,
                "author_link": author_link,
                "post_text": post_text,
                "post_url": post_url,
                "post_element": post_element,
                "source": "search"
            }

        except Exception as e:
            return None

    def _extract_person_from_search(self, card):
        """Extract person data from a search result card."""
        try:
            name = "Unknown"
            profile_url = ""
            profile_id = ""
            headline = ""

            try:
                name_elem = card.find_element(
                    By.CSS_SELECTOR, ".entity-result__title-text a"
                )
                name = name_elem.text.strip()
                profile_url = name_elem.get_attribute("href")
                if "/in/" in profile_url:
                    profile_id = profile_url.split("/in/")[1].split("/")[0].split("?")[0]
            except NoSuchElementException:
                pass

            try:
                headline_elem = card.find_element(
                    By.CSS_SELECTOR, ".entity-result__primary-subtitle"
                )
                headline = headline_elem.text.strip()
            except NoSuchElementException:
                pass

            location = ""
            try:
                loc_elem = card.find_element(
                    By.CSS_SELECTOR, ".entity-result__secondary-subtitle"
                )
                location = loc_elem.text.strip()
            except NoSuchElementException:
                pass

            return {
                "name": name,
                "profile_id": profile_id,
                "profile_url": profile_url,
                "headline": headline,
                "location": location
            }

        except Exception:
            return None

    def score_icp_for_person(self, person_data):
        """
        Score a search result person against the ICP.
        Returns (score, matched_keywords).
        """
        combined = f"{person_data.get('name', '')} {person_data.get('headline', '')}".lower()
        score = 0
        matched = []

        for kw in EXCLUDE_KEYWORDS:
            if kw.lower() in combined:
                return 0, []

        for kw in TARGET_KEYWORDS:
            if kw.lower() in combined:
                score += 25
                matched.append(kw)
                if score >= 50:
                    break

        # Seniority signals
        seniority = ["years", "experience", "scale", "team of", "revenue",
                     "led", "built", "founded", "grew", "managing", "director"]
        if any(s in combined for s in seniority):
            score += 10
            matched.append("seniority")

        return min(score, 100), matched

    def print_search_results(self, posts, show_all=False):
        """Print search results with ICP scoring."""
        if not posts:
            print("\n   No results found.")
            return

        print(f"\n{'='*60}")
        print(f"🔍 SEARCH RESULTS: {len(posts)} posts found")
        print(f"{'='*60}")

        for i, post in enumerate(posts, 1):
            author = post.get("author_name", "Unknown")
            headline = post.get("author_headline", "")[:60]
            text = post.get("post_text", "")[:120]

            # Quick ICP check
            combined = f"{author} {headline}".lower()
            icp_hits = [kw for kw in TARGET_KEYWORDS if kw.lower() in combined]

            icp_flag = "🎯" if icp_hits else "  "
            icp_label = f"[{', '.join(icp_hits[:3])}]" if icp_hits else "[not ICP]"

            print(f"\n#{i} {icp_flag} {author} {icp_label}")
            print(f"   {headline}")
            print(f"   {text}")
            print(f"   🔗 {post.get('post_url', '')}")

            if not show_all and i >= 15:
                remaining = len(posts) - i
                print(f"\n   ... and {remaining} more. Use --list {len(posts)} to see all.")
                break

        print(f"\n{'='*60}")
        icp_count = sum(1 for p in posts if any(
            kw.lower() in f"{p.get('author_name','')} {p.get('author_headline','')}".lower()
            for kw in TARGET_KEYWORDS
        ))
        print(f"🎯 {icp_count}/{len(posts)} match your ICP automatically")
        print(f"Run with --engage to engage with these posts")
        print(f"{'='*60}\n")
