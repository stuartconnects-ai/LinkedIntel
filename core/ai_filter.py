"""
LinkedIn Post AI Analysis Module
Analyzes posts using Google Gemini AI for engagement decisions.
Hardened: upgraded model, improved prompt quality, added ICP filtering.
"""
import json
import re
import time
from google import genai
from utils.parser import parse_ai_response
from config import (
    GEMINI_API_KEY,
    GEMINI_MODEL,
    TARGET_KEYWORDS,
    EXCLUDE_KEYWORDS,
    MIN_TARGET_MATCH_SCORE
)


class AIFilter:
    def __init__(self):
        self.client = genai.Client(api_key=GEMINI_API_KEY)
        self.model = GEMINI_MODEL

    def score_target_audience(self, post_data):
        """
        Score a post's author against the Ideal Customer Profile (ICP).
        Returns (score, reason) tuple. Score 0-100.
        """
        author_name = post_data.get("author_name", "").lower()
        headline = post_data.get("author_headline", "").lower()
        combined = f"{author_name} {headline}"

        score = 0
        reasons = []

        # Check inclusions
        for kw in TARGET_KEYWORDS:
            if kw.lower() in combined:
                score += 25
                reasons.append(f"+{kw}")
                # Cap at 2 matches max from keywords
                if len(reasons) >= 2:
                    break

        score = min(score, 50)  # Cap keyword score at 50

        # Check exclusions (instant rejection)
        for kw in EXCLUDE_KEYWORDS:
            if kw.lower() in combined:
                return 0, f"Excluded: '{kw}' in profile"

        # Check for seniority signals
        seniority_signals = ["years", "experience", "scale", "team of", "revenue",
                             "led", "built", "founded", "grew", "managing"]
        for signal in seniority_signals:
            if signal in combined:
                score += 10
                if len(reasons) < 3:
                    reasons.append("seniority")
                break

        # Check post content for business signals
        post_text = post_data.get("post_text", "").lower()
        business_signals = ["revenue", "team", "scale", "growth", "hire", "hiring",
                            "leadership", "strategy", "business", "company", "startup",
                            "client", "customer", "profit", "margin", "acquisition"]
        business_count = sum(1 for s in business_signals if s in post_text)
        score += min(business_count * 5, 40)

        if business_count > 2:
            reasons.append("business_content")

        reason_text = ", ".join(reasons) if reasons else "no ICP signals"
        return min(score, 100), reason_text

    def analyze_post(self, post_data):
        """
        Analyze a LinkedIn post and decide whether to like/comment.
        Returns structured decision dict.
        """
        try:
            post_text = post_data.get("post_text", "")
            author_name = post_data.get("author_name", "Unknown")
            author_headline = post_data.get("author_headline", "")

            if not post_text or len(post_text.strip()) < 30:
                return {
                    "should_like": False,
                    "should_comment": False,
                    "comment_text": "",
                    "reasoning": "Post too short or empty"
                }

            prompt = self._create_prompt(author_name, author_headline, post_text)

            response = self.client.models.generate_content(
                model=self.model,
                contents=prompt,
                config={
                    "temperature": 0.4,
                    "top_p": 0.8
                }
            )

            ai_response = response.text
            result = parse_ai_response(ai_response)

            # Force boolean checks (was a security fix in upstream)
            result["should_like"] = (
                str(result.get("should_like", "")).strip().lower() == "yes"
            )
            result["should_comment"] = (
                str(result.get("should_comment", "")).strip().lower() == "yes"
            )

            return result

        except Exception as e:
            print(f"❌ Error in AI analysis: {e}")
            return {
                "should_like": False,
                "should_comment": False,
                "comment_text": "",
                "reasoning": f"Analysis error: {str(e)[:100]}"
            }

    def _create_prompt(self, author_name, author_headline, post_text):
        """Create a calibrated prompt for engagement decisions."""
        return f"""You are a leadership and strategy engagement assistant for a coach who works with founders, CEOs, and business owners scaling past $250K revenue.

Your comments are calibrated, direct, and add genuine insight — never generic praise. You are selective: you only engage when you have something meaningful to add.

POST AUTHOR: {author_name}
AUTHOR HEADLINE: {author_headline}

POST CONTENT:
---
{post_text[:3000]}
---

Analyze this post and determine:

1. Does this post contain a claim, question, or perspective you could meaningfully add to or respectfully challenge?
2. Is it from someone in a founder, CEO, coach, or business owner role?
3. If engaging, write ONE comment (max 4 sentences, ideally 2-3) that:
   - Agrees with a SPECIFIC point and explains WHY, OR offers a calibrated counter-perspective
   - References a mechanism, experience, or observation (never vague encouragement)
   - Sounds like a real human executive, not a bot
   - NEVER starts with "Great post", "Thanks for sharing", "Well said", or similar platitudes
   - NEVER uses emoji or hashtags
   - Adds value to the conversation — the author should be glad you commented

IMPORTANT: Only recommend engagement if the post is substantive. Skip motivational quotes, AI-generated generic content, self-promotion without insight, and posts by non-decision-makers.

Format your response exactly like this (no markdown, no extra text):
LIKE: Yes or No
COMMENT: Yes or No
COMMENT_TEXT: [your comment here, or N/A if not commenting]
REASONING: [one line explanation]"""
