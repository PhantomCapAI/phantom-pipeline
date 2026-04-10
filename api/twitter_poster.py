"""
Twitter/X posting — posts approved drafts as threads via Twitter API v2.
"""

import os
import re
import tweepy

TWITTER_API_KEY = os.getenv("TWITTER_API_KEY", "")
TWITTER_API_SECRET = os.getenv("TWITTER_API_SECRET", "")
TWITTER_ACCESS_TOKEN = os.getenv("TWITTER_ACCESS_TOKEN", "")
TWITTER_ACCESS_TOKEN_SECRET = os.getenv("TWITTER_ACCESS_TOKEN_SECRET", "")


def get_client() -> tweepy.Client | None:
    if not all([TWITTER_API_KEY, TWITTER_API_SECRET, TWITTER_ACCESS_TOKEN, TWITTER_ACCESS_TOKEN_SECRET]):
        return None
    return tweepy.Client(
        consumer_key=TWITTER_API_KEY,
        consumer_secret=TWITTER_API_SECRET,
        access_token=TWITTER_ACCESS_TOKEN,
        access_token_secret=TWITTER_ACCESS_TOKEN_SECRET,
    )


def strip_hashtags(text: str) -> str:
    """Remove all hashtags from text."""
    return re.sub(r'\s*#\w+', '', text).strip()


def split_thread(text: str) -> list[str]:
    """Split numbered thread format (1/N, 2/N...) into individual tweets."""
    parts = re.split(r'\n\n(?=\d+/\d+\s)', text)
    if len(parts) == 1:
        parts = re.split(r'\n(?=\d+/\d+\s)', text)
    return [strip_hashtags(p.strip()) for p in parts if p.strip()]


def post_thread(text: str) -> list[dict]:
    """Post a thread to X. Returns list of {tweet_id, text} for each tweet."""
    client = get_client()
    if not client:
        raise RuntimeError("Twitter API keys not configured")

    tweets = split_thread(text)
    results = []
    previous_id = None

    for tweet_text in tweets:
        if not tweet_text:
            continue
        resp = client.create_tweet(
            text=tweet_text,
            in_reply_to_tweet_id=previous_id,
        )
        tweet_id = resp.data["id"]
        results.append({"tweet_id": tweet_id, "text": tweet_text})
        previous_id = tweet_id

    return results
