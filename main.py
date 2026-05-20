# main.py
"""
LinkedIntel — LinkedIn Engagement Intelligence Tool
Forked from PacemakerX/LinkedIntel. Hardened and extended for Limit Breaker Global.

Security fixes applied:
  - Removed --ignore-certificate-errors (MITM vulnerability)
  - Removed --allow-insecure-localhost (unnecessary)
  - Added load_dotenv() integration
  - Enforced daily action limits in all modes
  - Upgraded Gemini model to 2.5-flash
  - Added target audience (ICP) filtering

New modules:
  - ReplyTracker: monitors posts you've commented on for new replies
"""
import sys
import time
import random
import argparse
from pathlib import Path
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from webdriver_manager.chrome import ChromeDriverManager

# Import project modules
from config import HEADLESS_MODE, MAX_POSTS_TO_SCRAPE, MAX_COMMENTS_PER_DAY, MAX_LIKES_PER_DAY
from core.auth import LinkedInAuth
from core.feed_scrapper import FeedScraper
from core.ai_filter import AIFilter
from core.action_engine import ActionEngine
from core.reply_tracker import ReplyTracker


def setup_driver():
    """Set up and configure the Selenium WebDriver"""
    options = Options()
    if HEADLESS_MODE:
        options.add_argument("--headless")

    options.add_argument("--disable-notifications")
    options.add_argument("--start-maximized")
    options.add_argument("--disable-infobars")
    options.add_argument("--disable-extensions")
    options.add_argument("--incognito")
    # Security: SSL cert validation ENABLED (--ignore-certificate-errors REMOVED)
    # Security: insecure localhost DISABLED (--allow-insecure-localhost REMOVED)

    service = Service(ChromeDriverManager().install())
    return webdriver.Chrome(service=service, options=options)


def parse_arguments():
    """Parse command line arguments"""
    parser = argparse.ArgumentParser(description="LinkedIntel — LinkedIn Engagement Intelligence")
    parser.add_argument("--mode", choices=["feed", "replies", "full"], default="feed",
                        help="feed=analyze+engage | replies=check for new replies | full=both")
    parser.add_argument("--posts", type=int, default=MAX_POSTS_TO_SCRAPE,
                        help=f"Max posts to process (default: {MAX_POSTS_TO_SCRAPE})")
    parser.add_argument("--dry-run", action="store_true",
                        help="Analyze but don't perform any actions")
    parser.add_argument("--interactive", action="store_true",
                        help="Review each action before executing")

    return parser.parse_args()


def main():
    """Main application entry point"""
    print("=" * 50)
    print("LinkedIntel — LinkedIn Engagement Intelligence")
    print("=" * 50)

    args = parse_arguments()
    driver = None

    try:
        driver = setup_driver()
        auth = LinkedInAuth()

        if not auth.login(driver):
            print("Failed to log in to LinkedIn. Exiting.")
            return

        if args.mode in ("feed", "full"):
            process_feed(driver, args.posts, args.dry_run, args.interactive)

        if args.mode in ("replies", "full"):
            process_replies(driver, args.dry_run, args.interactive)

        print("\nCompleted successfully!")

    except KeyboardInterrupt:
        print("\nProcess interrupted by user. Exiting...")
    except Exception as e:
        print(f"Error in main execution: {e}")
    finally:
        if driver:
            try:
                driver.quit()
            except Exception:
                pass


def process_feed(driver, max_posts=10, dry_run=False, interactive=False):
    """Process LinkedIn feed posts with AI analysis and engagement"""
    print(f"\n📋 FEED MODE: Analyzing up to {max_posts} posts...")

    feed_scraper = FeedScraper()
    ai_filter = AIFilter()
    action_engine = ActionEngine()

    # Check daily limits before starting
    daily_comments = action_engine.get_daily_count("comments")
    daily_likes = action_engine.get_daily_count("likes")

    print(f"   Daily usage: {daily_comments}/{MAX_COMMENTS_PER_DAY} comments, "
          f"{daily_likes}/{MAX_LIKES_PER_DAY} likes")

    if daily_comments >= MAX_COMMENTS_PER_DAY and daily_likes >= MAX_LIKES_PER_DAY:
        print("⚠️  Daily limits reached. Skipping feed mode.")
        return

    posts = feed_scraper.scrape_feed(driver)
    processed = 0
    skipped_no_target = 0
    skipped_limits = 0

    for post in posts[:max_posts]:
        post_id = post.get("post_id", "unknown").split(":")[-1]
        author = post.get("author_name", "Unknown")
        headline = post.get("author_headline", "Unknown")

        print(f"\n--- Post {processed + 1}/{min(len(posts), max_posts)} ---")
        print(f"👤 {author} | {headline[:80]}")

        # Target audience filter
        match_score, match_reason = ai_filter.score_target_audience(post)
        print(f"🎯 ICP Score: {match_score}/100 — {match_reason}")

        if match_score < 40:
            print("   ⏭️  Skipped — not target audience")
            skipped_no_target += 1
            continue

        # Check daily limits
        if action_engine.get_daily_count("comments") >= MAX_COMMENTS_PER_DAY:
            print("   ⏭️  Skipped — daily comment limit reached")
            skipped_limits += 1
            continue

        # Analyze post with AI
        print("   🤖 Analyzing with AI...")
        analysis = ai_filter.analyze_post(post)

        print(f"   Like: {analysis.get('should_like', False)} | "
              f"Comment: {analysis.get('should_comment', False)}")
        if analysis.get('should_comment', False):
            comment_preview = analysis.get('comment_text', '')[:100]
            print(f"   💬 Comment: {comment_preview}...")

        # Interactive mode — ask for approval
        if interactive and analysis.get('should_comment', False):
            print("\n   --- PROPOSED COMMENT ---")
            print(f"   {analysis.get('comment_text', '')}")
            print("   ------------------------")
            choice = input("   Execute? [y]es/[n]o/[e]dit: ").strip().lower()
            if choice == 'n':
                analysis['should_comment'] = False
                analysis['should_like'] = False
            elif choice == 'e':
                new_comment = input("   Enter comment: ").strip()
                if new_comment:
                    analysis['comment_text'] = new_comment
                    analysis['should_comment'] = True
                else:
                    analysis['should_comment'] = False

        # Perform actions
        if not dry_run:
            results = action_engine.perform_actions(driver, post, analysis)
            print(f"   ✅ Liked: {results.get('liked')} | "
                  f"💬 Commented: {results.get('commented')}")
            if results.get("errors"):
                print(f"   ⚠️  Errors: {', '.join(results['errors'])}")
        else:
            print("   🔍 DRY RUN — no actions performed")

        processed += 1

        if processed < max_posts:
            delay = random.uniform(5, 10)
            print(f"   ⏳ Waiting {delay:.1f}s...")
            time.sleep(delay)

    print(f"\n📊 Feed complete: {processed} processed | "
          f"{skipped_no_target} skipped (not ICP) | "
          f"{skipped_limits} skipped (limits)")


def process_replies(driver, dry_run=False, interactive=False):
    """Check for new replies on posts we've previously commented on"""
    print("\n💬 REPLY MODE: Checking for new replies...")

    reply_tracker = ReplyTracker()

    # Get posts we've commented on recently
    new_replies = reply_tracker.check_for_replies(driver, dry_run=dry_run)

    if not new_replies:
        print("   ✅ No new replies found.")
        return

    print(f"\n   Found {len(new_replies)} new replies across "
          f"{len(set(r['post_id'] for r in new_replies))} posts:\n")

    for i, reply in enumerate(new_replies, 1):
        print(f"   #{i} — {reply['author_name']} replied on post {reply['post_id'][:12]}...")
        print(f"   📝 Your comment:  {reply['my_comment'][:80]}...")
        print(f"   ↩️  Their reply:   {reply['reply_text'][:120]}...")
        print(f"   🔗 Post: {reply.get('post_url', 'N/A')}")
        print()

    if not dry_run:
        reply_tracker.mark_replies_seen([r['reply_id'] for r in new_replies])
        print(f"   ✅ Marked {len(new_replies)} replies as seen.")


if __name__ == "__main__":
    main()
