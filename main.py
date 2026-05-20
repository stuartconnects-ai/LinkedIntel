# main.py
"""
LinkedIntel — LinkedIn Engagement Intelligence Tool
Forked from PacemakerX/LinkedIntel. Hardened and extended for Limit Breaker Global.

Modes:
  --mode feed       Analyze feed, filter by ICP, engage with target audience
  --mode replies    Check posts you've commented on for new replies
  --mode priority   Show daily priority engagement list
  --mode full       Feed + replies (complete cycle)
  --mode stats      Contact database statistics summary

Architecture:
  Feed → ICP Filter → AI Analysis → Engagement → Contact DB
  Reply Tracker → Contact DB (records replies)
  Contact Manager → Daily Priority List (who to engage today)
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

from config import HEADLESS_MODE, MAX_POSTS_TO_SCRAPE, MAX_COMMENTS_PER_DAY, MAX_LIKES_PER_DAY
from core.auth import LinkedInAuth
from core.feed_scrapper import FeedScraper
from core.ai_filter import AIFilter
from core.action_engine import ActionEngine
from core.reply_tracker import ReplyTracker
from core.contact_manager import ContactManager


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

    service = Service(ChromeDriverManager().install())
    return webdriver.Chrome(service=service, options=options)


def parse_arguments():
    parser = argparse.ArgumentParser(description="LinkedIntel — LinkedIn Engagement Intelligence")
    parser.add_argument("--mode", choices=["feed", "replies", "priority", "full", "stats", "contact"],
                        default="priority", help="Operating mode")
    parser.add_argument("--posts", type=int, default=MAX_POSTS_TO_SCRAPE,
                        help=f"Max posts to process (default: {MAX_POSTS_TO_SCRAPE})")
    parser.add_argument("--list", type=int, default=15,
                        help="Number of contacts in priority list (default: 15)")
    parser.add_argument("--dry-run", action="store_true",
                        help="Analyze but don't perform any actions")
    parser.add_argument("--interactive", action="store_true",
                        help="Review each action before executing")
    parser.add_argument("--contact", type=str, default="",
                        help="Show detailed history for a contact (by name or ID)")
    parser.add_argument("--tag", type=str, default="",
                        help="Tag a contact (use with --contact)")
    parser.add_argument("--note", type=str, default="",
                        help="Add a note to a contact (use with --contact)")

    return parser.parse_args()


def main():
    print("=" * 50)
    print("LinkedIntel — LinkedIn Engagement Intelligence")
    print("=" * 50)

    args = parse_arguments()
    cm = ContactManager()

    # ── Modes that don't need browser ──

    if args.mode == "priority":
        cm.print_priority_list(args.list)
        return

    if args.mode == "stats":
        stats = cm.get_stats()
        print(f"\n📊 Contact Database Stats")
        print(f"   Total contacts:      {stats['total_contacts']}")
        print(f"   🔥 Hot (replied):     {stats['by_tier']['hot']}")
        print(f"   🟡 Warm (rapport):    {stats['by_tier']['warm']}")
        print(f"   🟢 New (ICP match):   {stats['by_tier']['new']}")
        print(f"   ⚪ Cold (dormant):    {stats['by_tier']['cold']}")
        print(f"   Total interactions:  {stats['total_interactions']}")
        print(f"   Replies received:    {stats['total_replies_received']}")
        print(f"   DB size:             {stats['database_size_kb']} KB")
        return

    if args.mode == "contact":
        contact_id = args.contact
        if contact_id:
            # Try to find by name (partial match) or by ID
            found = None
            for cid, c in cm.contacts.items():
                if cid.startswith(contact_id) or contact_id.lower() in c.get("name", "").lower():
                    found = cid
                    break
            if found:
                if args.tag:
                    cm.add_tags(found, [args.tag])
                    print(f"✅ Tagged contact with: {args.tag}")
                if args.note:
                    cm.add_note(found, args.note)
                    print(f"✅ Added note to contact")
                cm.print_contact_detail(found)
            else:
                print(f"Contact not found: {contact_id}")
        else:
            print("Usage: --mode contact --contact <name or ID> [--tag TAG] [--note NOTE]")
        return

    # ── Modes that need browser ──

    driver = None
    try:
        driver = setup_driver()
        auth = LinkedInAuth()

        if not auth.login(driver):
            print("Failed to log in to LinkedIn. Exiting.")
            return

        if args.mode in ("feed", "full"):
            process_feed(driver, cm, args.posts, args.dry_run, args.interactive)

        if args.mode in ("replies", "full"):
            process_replies(driver, cm, args.dry_run, args.interactive)

        # Show priority list after engagement
        if args.mode in ("feed", "replies", "full"):
            cm.recalculate_all()
            cm.print_priority_list(min(args.list, 10))

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


def process_feed(driver, cm, max_posts=10, dry_run=False, interactive=False):
    """Process LinkedIn feed: filter by ICP, analyze, engage, record contacts."""
    print(f"\n📋 FEED MODE: Analyzing up to {max_posts} posts...")

    feed_scraper = FeedScraper()
    ai_filter = AIFilter()
    action_engine = ActionEngine()

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
        post_url = post.get("post_url", "")
        author = post.get("author_name", "Unknown")
        headline = post.get("author_headline", "Unknown")
        profile_url = post.get("author_link", "")

        print(f"\n--- Post {processed + 1}/{min(len(posts), max_posts)} ---")
        print(f"👤 {author} | {headline[:80]}")

        # Register contact in database (even if we don't engage)
        contact = cm.record_seen_in_feed(author, profile_url, headline)
        if not contact:
            print("   ⏭️  Skipped — not target audience (excluded or low ICP)")
            skipped_no_target += 1
            continue

        icp_score = contact.get("icp_score", 0)
        contact_tier = contact.get("tier", "cold")
        tier_emoji = {"hot": "🔥", "warm": "🟡", "new": "🟢", "cold": "⚪"}.get(contact_tier, "")
        print(f"   🎯 ICP: {icp_score}/100 — {tier_emoji} Tier: {contact_tier} "
              f"({contact.get('interactions', 0)}x engaged)")

        if icp_score < 40:
            print("   ⏭️  Skipped — below ICP threshold")
            skipped_no_target += 1
            continue

        # Daily limits
        if action_engine.get_daily_count("comments") >= MAX_COMMENTS_PER_DAY:
            print("   ⏭️  Skipped — daily comment limit reached")
            skipped_limits += 1
            continue

        # AI analysis
        print("   🤖 Analyzing with AI...")
        analysis = ai_filter.analyze_post(post)

        should_engage = analysis.get("should_like", False) or analysis.get("should_comment", False)
        print(f"   Like: {analysis.get('should_like', False)} | "
              f"Comment: {analysis.get('should_comment', False)}")

        if analysis.get("should_comment", False):
            comment_preview = analysis.get("comment_text", "")[:100]
            print(f"   💬 Comment: {comment_preview}...")

        if not should_engage:
            print("   ⏭️  AI chose not to engage (no valuable angle)")
            continue

        # Interactive review
        if interactive and analysis.get("should_comment", False):
            print("\n   --- PROPOSED COMMENT ---")
            print(f"   {analysis.get('comment_text', '')}")
            print("   ------------------------")
            choice = input("   Execute? [y]es/[n]o/[e]dit: ").strip().lower()
            if choice == "n":
                analysis["should_comment"] = False
                analysis["should_like"] = False
            elif choice == "e":
                new_comment = input("   Enter comment: ").strip()
                if new_comment:
                    analysis["comment_text"] = new_comment
                    analysis["should_comment"] = True
                else:
                    analysis["should_comment"] = False

        # Perform actions
        if not dry_run:
            results = action_engine.perform_actions(driver, post, analysis)
            liked = results.get("liked", False)
            commented = results.get("commented", False)
            comment_text = results.get("comment_text", "")

            print(f"   ✅ Liked: {liked} | 💬 Commented: {commented}")

            # Record engagement in contact database
            if commented or liked:
                cm.record_engagement(
                    author, profile_url, headline,
                    post_id, post_url, comment_text
                )

            if results.get("errors"):
                print(f"   ⚠️  Errors: {', '.join(results['errors'])}")
        else:
            print("   🔍 DRY RUN — no actions performed")

        processed += 1

        if processed < max_posts:
            delay = random.uniform(5, 10)
            print(f"   ⏳ Waiting {delay:.1f}s...")
            time.sleep(delay)

    print(f"\n📊 Feed complete: {processed} engaged | "
          f"{skipped_no_target} skipped (not ICP) | "
          f"{skipped_limits} skipped (limits)")


def process_replies(driver, cm, dry_run=False, interactive=False):
    """Check for new replies and record them in the contact database."""
    print("\n💬 REPLY MODE: Checking for new replies...")

    reply_tracker = ReplyTracker()
    new_replies = reply_tracker.check_for_replies(driver, dry_run=dry_run)

    if not new_replies:
        print("   ✅ No new replies found.")
        return

    print(f"\n   Found {len(new_replies)} new replies across "
          f"{len(set(r['post_id'] for r in new_replies))} posts:\n")

    for i, reply in enumerate(new_replies, 1):
        post_id = reply.get("post_id", "")
        post_url = reply.get("post_url", "")
        author_name = reply.get("author_name", "Unknown")
        author_headline = reply.get("author_headline", "")
        reply_text = reply.get("reply_text", "")
        my_comment = reply.get("my_comment", "")

        print(f"   #{i} — {author_name} replied on post {post_id[:12]}...")
        print(f"   📝 Your comment:  {my_comment[:80]}...")
        print(f"   ↩️  Their reply:   {reply_text[:120]}...")
        print(f"   🔗 Post: {post_url}")
        print()

        # Record in contact database (creates contact if new, bumps to Hot tier)
        if not dry_run:
            cm.record_reply_received(
                author_name, "", author_headline,
                post_id, post_url, reply_text
            )

    if not dry_run:
        reply_tracker.mark_replies_seen([r["reply_id"] for r in new_replies])
        print(f"   ✅ Marked {len(new_replies)} replies as seen.")
        print(f"   🔥 These contacts are now in your HOT tier — engage today!")


if __name__ == "__main__":
    main()
