"""
LinkedIntel → Google Sheets Sync

Syncs the ContactManager database (data/contacts.json) to a
"LinkedIntel Contacts" tab in the master tracker spreadsheet.

Run standalone:  node scripts/linkedintel-sheets-sync.mjs
Run from Python: python main.py --mode sync

Two-way: reads back manual edits (tags, notes, tier overrides)
          and merges them into the local database.
"""
import json
import time
import subprocess
from pathlib import Path
from datetime import datetime
from core.contact_manager import ContactManager
from config import DATA_DIR

# Node.js sync script path (relative to workspace)
SYNC_SCRIPT = Path(__file__).parent.parent.parent / "scripts" / "linkedintel-sheets-sync.mjs"

# Tab name in the master tracker spreadsheet
SHEET_TAB_NAME = "LinkedIntel Contacts"

# Columns for the sheet
COLUMNS = [
    "Contact ID",
    "Name",
    "Headline",
    "Profile URL",
    "ICP Score",
    "Priority Score",
    "Tier",
    "Interactions",
    "Replies Received",
    "Unread Replies",
    "First Seen",
    "Last Engaged",
    "Last Posted",
    "Tags",
    "Notes",
]


def sync_to_sheets():
    """
    Sync contacts database to Google Sheets.
    Uses the existing Node.js Google Sheets auth infrastructure.
    """
    cm = ContactManager()

    if not cm.contacts:
        print("No contacts to sync. Database is empty.")
        return False

    # Build rows for sheets
    rows = [COLUMNS]  # Header row

    # Sort by priority score descending
    sorted_contacts = sorted(
        cm.contacts.values(),
        key=lambda c: c.get("priority_score", 0),
        reverse=True
    )

    for contact in sorted_contacts:
        unread_replies = sum(
            1 for r in contact.get("replies_received", [])
            if r.get("status") == "new"
        )

        row = [
            contact.get("contact_id", ""),
            contact.get("name", ""),
            contact.get("headline", ""),
            contact.get("profile_url", ""),
            contact.get("icp_score", 0),
            contact.get("priority_score", 0),
            contact.get("tier", ""),
            contact.get("interactions", 0),
            len(contact.get("replies_received", [])),
            unread_replies,
            _format_date(contact.get("first_seen")),
            _format_date(contact.get("last_engaged")),
            _format_date(contact.get("last_posted")),
            ", ".join(contact.get("tags", [])),
            contact.get("notes", ""),
        ]
        rows.append(row)

    # Write to temp JSON for Node.js script to consume
    temp_path = Path(DATA_DIR) / "_sheets_sync_payload.json"
    temp_path.write_text(json.dumps({
        "tabName": SHEET_TAB_NAME,
        "columns": COLUMNS,
        "rows": rows,
    }, default=str))

    print(f"📊 Syncing {len(sorted_contacts)} contacts to Google Sheets...")
    print(f"   Tab: {SHEET_TAB_NAME}")
    print(f"   🔥 Hot: {sum(1 for c in sorted_contacts if c.get('tier') == 'hot')}")
    print(f"   🟡 Warm: {sum(1 for c in sorted_contacts if c.get('tier') == 'warm')}")
    print(f"   🟢 New: {sum(1 for c in sorted_contacts if c.get('tier') == 'new')}")

    # Call Node.js sync script
    try:
        result = subprocess.run(
            ["node", str(SYNC_SCRIPT), str(temp_path)],
            capture_output=True, text=True, timeout=30
        )
        if result.returncode == 0:
            print(result.stdout)
        else:
            print(f"❌ Sync failed: {result.stderr}")
            return False
    except Exception as e:
        print(f"❌ Sync error: {e}")
        return False

    temp_path.unlink(missing_ok=True)
    return True


def sync_from_sheets():
    """
    Read back data from the Google Sheets tab and merge into contacts.json.
    Allows manual edits in sheets (tags, notes, tier overrides).
    """
    # Call Node.js script to pull sheet data
    try:
        result = subprocess.run(
            ["node", str(SYNC_SCRIPT), "--pull"],
            capture_output=True, text=True, timeout=30
        )
        if result.returncode != 0:
            print(f"❌ Pull failed: {result.stderr}")
            return False
    except Exception as e:
        print(f"❌ Pull error: {e}")
        return False

    # Parse the returned data
    try:
        sheet_data = json.loads(result.stdout)
    except json.JSONDecodeError:
        print("❌ Could not parse sheet data")
        return False

    cm = ContactManager()
    merged = 0

    for row in sheet_data.get("rows", []):
        contact_id = row[0] if len(row) > 0 else ""
        if not contact_id or contact_id == "Contact ID":
            continue

        contact = cm.contacts.get(contact_id)
        if not contact:
            continue

        # Merge sheet values back (tags, notes, manual tier override)
        sheet_notes = row[14] if len(row) > 14 else ""
        sheet_tags = [t.strip() for t in (row[13] or "").split(",") if t.strip()]

        if sheet_notes and sheet_notes != contact.get("notes", ""):
            contact["notes"] = sheet_notes
            merged += 1

        existing_tags = set(contact.get("tags", []))
        if set(sheet_tags) != existing_tags:
            contact["tags"] = sheet_tags
            merged += 1

    cm._save()
    print(f"✅ Pulled {len(sheet_data.get('rows', []))} rows, merged {merged} changes")
    return True


def _format_date(timestamp):
    """Format Unix timestamp to human-readable date."""
    if not timestamp:
        return ""
    return datetime.fromtimestamp(timestamp).strftime("%d %b %Y, %H:%M")


# Allow direct execution from linkedintel directory
if __name__ == "__main__":
    import sys
    from config import DATA_DIR
    if "--pull" in sys.argv:
        sync_from_sheets()
    else:
        sync_to_sheets()
