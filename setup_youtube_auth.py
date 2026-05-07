"""
One-time OAuth setup for YouTube.
Run this script once per channel to authorize the app to upload videos.

Steps:
  1. Create a Google Cloud project and enable "YouTube Data API v3"
  2. Create OAuth 2.0 Desktop credentials and download the JSON
  3. Save it as config/youtube_client_secrets_<channel_id>.json
  4. Run: python setup_youtube_auth.py --channel <channel_id>
  5. A browser window will open — log in with the YouTube account
  6. The refresh token is saved to config/youtube_tokens_<channel_id>.json
     (this file is gitignored for security)
"""
import argparse
import json
import sys
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

from google_auth_oauthlib.flow import InstalledAppFlow
from src.utils.logger import get_logger

logger = get_logger("setup_auth")

SCOPES = ["https://www.googleapis.com/auth/youtube.upload"]


def main() -> None:
    parser = argparse.ArgumentParser(description="Set up YouTube OAuth for a channel.")
    parser.add_argument(
        "--channel",
        required=True,
        help="Channel ID matching channels.json (e.g. channel_main)",
    )
    args = parser.parse_args()

    secrets_path = Path(f"config/youtube_client_secrets_{args.channel}.json")
    tokens_path = Path(f"config/youtube_tokens_{args.channel}.json")

    if not secrets_path.exists():
        print(f"\nERROR: Client secrets file not found: {secrets_path}")
        print("\nTo create it:")
        print("  1. Go to https://console.cloud.google.com")
        print("  2. Create a project (or use an existing one)")
        print("  3. Enable 'YouTube Data API v3'")
        print("  4. Go to APIs & Services → Credentials")
        print("  5. Create OAuth 2.0 Client ID (type: Desktop app)")
        print(f"  6. Download JSON and save it as: {secrets_path}")
        sys.exit(1)

    print(f"\nStarting OAuth flow for channel: {args.channel}")
    print("A browser window will open. Log in with the YouTube account you want to use.\n")

    flow = InstalledAppFlow.from_client_secrets_file(str(secrets_path), SCOPES)
    creds = flow.run_local_server(port=0)

    tokens_path.parent.mkdir(parents=True, exist_ok=True)
    with open(tokens_path, "w") as f:
        f.write(creds.to_json())

    print(f"\n✅ Success! Credentials saved to: {tokens_path}")
    print("   This file contains your refresh token — keep it secure and never commit it.")
    print(f"\n   You can now run: python run_once.py --channel {args.channel}")


if __name__ == "__main__":
    main()
