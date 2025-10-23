#!/usr/bin/env python3
"""
Nostr to Bluesky Cross-Poster Bot

Monitors a specific Nostr user's kind 1 notes (excluding replies)
and automatically cross-posts them to Bluesky.
"""

import os
import sys
import time
import asyncio
import logging
import re
import json
from io import BytesIO
from datetime import datetime, timezone
from typing import Optional, Set, List, Tuple, Dict

import httpx
from PIL import Image
from dotenv import load_dotenv
from nostr_sdk import (
    Client, Filter, PublicKey, Event, RelayMessage,
    Kind, Timestamp, RelayUrl, init_logger, LogLevel
)
from atproto import Client as BlueskyClient, client_utils, models

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('bot.log'),
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger('nostr-bluesky-bot')


class NotificationHandler:
    """Handler for Nostr notifications"""

    def __init__(self, bot):
        self.bot = bot

    async def handle(self, relay_url: RelayUrl, subscription_id: str, event: Event):
        """Handle incoming events"""
        # Process the event
        await self.bot.handle_nostr_event(event)

    async def handle_msg(self, relay_url: RelayUrl, msg: RelayMessage):
        """Handle relay messages"""
        # Can be used for debugging relay messages if needed
        pass


class NostrToBlueskyBot:
    """Bot that cross-posts Nostr notes to Bluesky"""

    def __init__(self):
        """Initialize the bot with configuration from environment variables"""
        load_dotenv()

        # Load and validate configuration
        self.nostr_relay = os.getenv('NOSTR_RELAY')
        self.bluesky_username = os.getenv('BLUESKY_USERNAME')
        self.bluesky_password = os.getenv('BLUESKY_APP_PASSWORD')

        if not all([self.nostr_relay, self.bluesky_username, self.bluesky_password]):
            raise ValueError("Missing required environment variables. Check .env file.")

        # Get Nostr public key (support both npub and hex formats)
        npub = os.getenv('NOSTR_NPUB')
        hex_pubkey = os.getenv('NOSTR_PUBKEY')

        if npub:
            self.nostr_pubkey = PublicKey.parse(npub)
            logger.info(f"Monitoring Nostr npub: {npub}")
        elif hex_pubkey:
            self.nostr_pubkey = PublicKey.parse(hex_pubkey)
            logger.info(f"Monitoring Nostr pubkey: {hex_pubkey}")
        else:
            raise ValueError("Must provide either NOSTR_NPUB or NOSTR_PUBKEY")

        # Initialize clients
        self.nostr_client: Optional[Client] = None
        self.bluesky_client: Optional[BlueskyClient] = None

        # Track processed events to avoid duplicates
        self.processed_events: Set[str] = set()

        # Track bot start time to avoid posting old notes
        self.start_time = Timestamp.now()

    def is_reply(self, event: Event) -> bool:
        """Check if a note is a reply by examining its tags"""
        tags = event.tags()

        # A note is considered a reply if it has 'e' tags (referencing other events)
        # The event_ids() method extracts all event IDs from 'e' tags
        event_ids = tags.event_ids()

        # If there are any event IDs, this is a reply
        return len(event_ids) > 0

    async def connect_nostr(self):
        """Connect to Nostr relay and set up subscription"""
        logger.info("Connecting to Nostr relay...")

        # Initialize Nostr SDK logger
        init_logger(LogLevel.INFO)

        # Create Nostr client
        self.nostr_client = Client()

        # Add relay
        relay_url = RelayUrl.parse(self.nostr_relay)
        await self.nostr_client.add_relay(relay_url)
        logger.info(f"Added relay: {self.nostr_relay}")

        # Connect to relay
        await self.nostr_client.connect()
        logger.info("Connected to Nostr relay")

    async def connect_bluesky(self):
        """Authenticate with Bluesky"""
        logger.info("Connecting to Bluesky...")

        self.bluesky_client = BlueskyClient()
        self.bluesky_client.login(self.bluesky_username, self.bluesky_password)

        logger.info(f"Authenticated with Bluesky as {self.bluesky_username}")

    def extract_image_urls(self, content: str) -> List[str]:
        """Extract image URLs from note content"""
        # Common image URL patterns (jpg, jpeg, png, gif, webp)
        image_pattern = r'https?://[^\s]+\.(?:jpg|jpeg|png|gif|webp|JPG|JPEG|PNG|GIF|WEBP)'

        urls = re.findall(image_pattern, content)

        # Clean up URLs (remove trailing punctuation that might be part of sentence)
        cleaned_urls = []
        for url in urls:
            # Remove trailing punctuation
            url = re.sub(r'[.,;:!?)\]]+$', '', url)
            cleaned_urls.append(url)

        return cleaned_urls

    def remove_image_urls(self, content: str, image_urls: List[str]) -> str:
        """Remove image URLs from content since they'll be attached as images"""
        cleaned_content = content

        for url in image_urls:
            # Remove the URL (with or without trailing punctuation)
            cleaned_content = re.sub(re.escape(url) + r'[.,;:!?)\]]*', '', cleaned_content)

        # Clean up extra whitespace
        # Remove multiple spaces
        cleaned_content = re.sub(r' +', ' ', cleaned_content)
        # Remove multiple newlines (keep max 2 consecutive)
        cleaned_content = re.sub(r'\n{3,}', '\n\n', cleaned_content)
        # Remove leading/trailing whitespace
        cleaned_content = cleaned_content.strip()

        return cleaned_content

    def extract_npub_mentions(self, content: str) -> List[str]:
        """Extract nostr:npub mentions from content"""
        # Pattern to match nostr:npub followed by bech32 encoded public key
        npub_pattern = r'nostr:(npub1[qpzry9x8gf2tvdw0s3jn54khce6mua7l]+)'
        matches = re.findall(npub_pattern, content)
        return matches

    async def fetch_profile_metadata(self, npub: str) -> Optional[Dict[str, str]]:
        """
        Fetch profile metadata for a given npub
        Returns dict with 'name' and 'display_name' fields or None if failed
        """
        try:
            # Parse the npub to get the public key
            pubkey = PublicKey.parse(npub)

            # Create a filter for kind 0 events (user metadata) for this pubkey
            metadata_filter = Filter().author(pubkey).kind(Kind(0)).limit(1)

            # Query the relay for metadata
            # Use get_events_of with a timeout
            events = await self.nostr_client.get_events_of(
                [metadata_filter],
                timeout=5  # 5 second timeout
            )

            if not events or len(events) == 0:
                logger.debug(f"No metadata found for {npub}")
                return None

            # Get the most recent metadata event
            metadata_event = events[0]
            content = metadata_event.content()

            # Parse the JSON metadata
            metadata = json.loads(content)

            # Extract name or display_name
            display_name = metadata.get('display_name') or metadata.get('name') or None

            if display_name:
                logger.info(f"Found display name '{display_name}' for {npub}")
                return {'display_name': display_name, 'name': metadata.get('name', '')}
            else:
                logger.debug(f"No display name found in metadata for {npub}")
                return None

        except json.JSONDecodeError as e:
            logger.warning(f"Failed to parse metadata JSON for {npub}: {e}")
            return None
        except Exception as e:
            logger.warning(f"Failed to fetch metadata for {npub}: {e}")
            return None

    async def replace_npub_mentions(self, content: str) -> str:
        """
        Replace nostr:npub mentions with display names
        Example: 'hello nostr:npub1v5u...' -> 'hello Fountain'
        """
        # Extract all npub mentions
        npubs = self.extract_npub_mentions(content)

        if not npubs:
            return content

        logger.info(f"Found {len(npubs)} npub mention(s) to resolve")

        # Create a copy of content to modify
        modified_content = content

        # Fetch metadata for each unique npub
        for npub in set(npubs):  # Use set to avoid duplicate fetches
            metadata = await self.fetch_profile_metadata(npub)

            if metadata and metadata.get('display_name'):
                display_name = metadata['display_name']
                # Replace all occurrences of nostr:npub with the display name
                mention_pattern = f"nostr:{npub}"
                modified_content = modified_content.replace(mention_pattern, display_name)
                logger.info(f"Replaced {mention_pattern} with '{display_name}'")
            else:
                # If we can't fetch metadata, keep the npub but remove the nostr: prefix
                mention_pattern = f"nostr:{npub}"
                modified_content = modified_content.replace(mention_pattern, npub)
                logger.debug(f"Could not resolve {npub}, keeping npub without prefix")

        return modified_content

    async def download_image(self, url: str, max_size_mb: int = 10) -> Optional[Tuple[bytes, str]]:
        """
        Download an image from a URL
        Returns tuple of (image_bytes, mime_type) or None if failed
        """
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.get(url, follow_redirects=True)
                response.raise_for_status()

                # Check content type
                content_type = response.headers.get('content-type', '')
                if not content_type.startswith('image/'):
                    logger.warning(f"URL is not an image: {url} (type: {content_type})")
                    return None

                # Check size
                content = response.content
                size_mb = len(content) / (1024 * 1024)
                if size_mb > max_size_mb:
                    logger.warning(f"Image too large: {size_mb:.2f}MB (max: {max_size_mb}MB)")
                    return None

                # Validate it's a real image by trying to open it
                try:
                    img = Image.open(BytesIO(content))
                    img.verify()
                except Exception as e:
                    logger.warning(f"Invalid image file: {e}")
                    return None

                logger.info(f"Downloaded image: {url} ({size_mb:.2f}MB, {content_type})")
                return (content, content_type)

        except Exception as e:
            logger.error(f"Failed to download image {url}: {e}")
            return None

    async def upload_image_to_bluesky(self, image_data: bytes) -> Optional[dict]:
        """Upload image to Bluesky and return the blob reference"""
        try:
            # Upload the image blob
            blob = self.bluesky_client.upload_blob(image_data)
            return blob
        except Exception as e:
            logger.error(f"Failed to upload image to Bluesky: {e}")
            return None

    async def post_to_bluesky(self, content: str, image_urls: Optional[List[str]] = None) -> bool:
        """Post content to Bluesky with optional images"""
        try:
            # Download and upload images if provided
            images = []
            successfully_processed_urls = []

            if image_urls:
                logger.info(f"Processing {len(image_urls)} image(s)...")

                for url in image_urls[:4]:  # Bluesky supports max 4 images
                    image_data = await self.download_image(url)
                    if image_data:
                        image_bytes, mime_type = image_data
                        blob = await self.upload_image_to_bluesky(image_bytes)
                        if blob:
                            # Create image embed
                            images.append(models.AppBskyEmbedImages.Image(
                                alt="Image from Nostr",
                                image=blob.blob
                            ))
                            successfully_processed_urls.append(url)

            # Remove image URLs from content since they're attached as images
            post_content = content
            if successfully_processed_urls:
                post_content = self.remove_image_urls(content, successfully_processed_urls)
                logger.info(f"Removed {len(successfully_processed_urls)} image URL(s) from text")

            # Build the post
            if images:
                # Post with images
                embed = models.AppBskyEmbedImages.Main(images=images)
                self.bluesky_client.send_post(text=post_content, embed=embed)
                logger.info(f"Successfully posted to Bluesky with {len(images)} image(s)")
            else:
                # Text-only post
                text_builder = client_utils.TextBuilder()
                text_builder.text(post_content)
                self.bluesky_client.send_post(text_builder)
                logger.info("Successfully posted to Bluesky")

            return True

        except Exception as e:
            logger.error(f"Failed to post to Bluesky: {e}", exc_info=True)
            return False

    async def handle_nostr_event(self, event: Event):
        """Process a Nostr event and post to Bluesky if appropriate"""
        event_id = event.id().to_hex()

        # Skip if already processed
        if event_id in self.processed_events:
            return

        # Skip if event is older than bot start time
        if event.created_at().as_secs() < self.start_time.as_secs():
            return

        # Mark as processed
        self.processed_events.add(event_id)

        # Skip if it's a reply
        if self.is_reply(event):
            logger.debug(f"Skipping reply event: {event_id}")
            return

        # Get note content
        content = event.content()

        if not content.strip():
            logger.debug(f"Skipping empty event: {event_id}")
            return

        # Log the note
        author = event.author().to_bech32()
        timestamp = datetime.fromtimestamp(event.created_at().as_secs(), tz=timezone.utc)
        logger.info(f"New note from {author} at {timestamp}")
        logger.info(f"Content preview: {content[:100]}...")

        # Replace nostr:npub mentions with display names
        content = await self.replace_npub_mentions(content)

        # Extract image URLs from content
        image_urls = self.extract_image_urls(content)
        if image_urls:
            logger.info(f"Found {len(image_urls)} image(s) in note")

        # Post to Bluesky with images if present
        success = await self.post_to_bluesky(content, image_urls if image_urls else None)

        if success:
            logger.info(f"✓ Cross-posted event {event_id[:8]}... to Bluesky")
        else:
            logger.error(f"✗ Failed to cross-post event {event_id[:8]}...")

    async def listen(self):
        """Main listening loop for Nostr events"""
        logger.info("Starting to listen for Nostr events...")

        # Create filter for kind 1 notes from the specific user
        # Only get events from now onwards
        nostr_filter = Filter().author(self.nostr_pubkey).kind(Kind(1)).since(self.start_time)

        logger.info(f"Subscribing to kind 1 notes from {self.nostr_pubkey.to_bech32()}")
        logger.info(f"Filtering events since: {datetime.fromtimestamp(self.start_time.as_secs(), tz=timezone.utc)}")

        # Subscribe to filter
        await self.nostr_client.subscribe(nostr_filter)

        logger.info("Listening for new notes... (Press Ctrl+C to stop)")

        # Create notification handler
        handler = NotificationHandler(self)

        # Handle notifications continuously
        try:
            await self.nostr_client.handle_notifications(handler)
        except KeyboardInterrupt:
            logger.info("Received shutdown signal")
        except Exception as e:
            logger.error(f"Error in listen loop: {e}", exc_info=True)
            raise

    async def run(self):
        """Start the bot"""
        try:
            # Connect to services
            await self.connect_nostr()
            await self.connect_bluesky()

            # Start listening
            await self.listen()

        except KeyboardInterrupt:
            logger.info("Bot stopped by user")
        except Exception as e:
            logger.error(f"Fatal error: {e}", exc_info=True)
            raise
        finally:
            # Cleanup
            if self.nostr_client:
                await self.nostr_client.shutdown()
            logger.info("Bot shutdown complete")


async def main():
    """Entry point"""
    try:
        bot = NostrToBlueskyBot()
        await bot.run()
    except Exception as e:
        logger.error(f"Failed to start bot: {e}", exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
