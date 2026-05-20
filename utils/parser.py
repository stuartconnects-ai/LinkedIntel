"""
AI Response Parser — extracts engagement decisions from Gemini output.
Hardened: anchored regex patterns to prevent false matches.
"""
import re


def parse_ai_response(response: str):
    """
    Parses the AI response and extracts engagement decisions.
    Uses anchored patterns to avoid false matches from content
    containing the keywords LIKE/COMMENT/REASONING elsewhere.
    """
    try:
        # Anchored patterns: match only at line-start, case-insensitive
        like_match = re.search(r"^(?:\*\*)?LIKE:\s*(Yes|No)(?:\*\*)?", response, re.IGNORECASE | re.MULTILINE)
        comment_match = re.search(r"^(?:\*\*)?COMMENT:\s*(Yes|No)(?:\*\*)?", response, re.IGNORECASE | re.MULTILINE)
        comment_text_match = re.search(r"^COMMENT_TEXT:\s*(.*?)$", response, re.MULTILINE)
        reasoning_match = re.search(r"^REASONING:\s*(.*?)$", response, re.MULTILINE)

        should_like = like_match.group(1).strip() if like_match else "No"
        should_comment = comment_match.group(1).strip() if comment_match else "No"
        comment_text = comment_text_match.group(1).strip() if comment_text_match else ""
        reasoning = reasoning_match.group(1).strip() if reasoning_match else "No reasoning provided"

        # Validate comment_text — if COMMENT=No, ignore stale COMMENT_TEXT
        if should_comment.lower() == "no":
            comment_text = ""

        return {
            "should_like": should_like,
            "should_comment": should_comment,
            "comment_text": comment_text,
            "reasoning": reasoning
        }

    except Exception as e:
        print(f"Error parsing AI response: {str(e)}")
        return {
            "should_like": "No",
            "should_comment": "No",
            "comment_text": "",
            "reasoning": "Error: Unable to parse the response."
        }
