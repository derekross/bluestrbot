# Nostr to Bluesky Cross-Poster Bot

A Python bot that automatically cross-posts Nostr kind 1 notes (text posts) from a specific user to Bluesky. The bot filters out replies, automatically handles images, and only posts original notes.

## Quick Start

```bash
# 1. Install dependencies
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# 2. Configure
cp .env.example .env
nano .env  # Add your credentials

# 3. Run
python bot.py
```

For running as a system service, see the [Running as a System Service](#running-as-a-system-service-recommended) section.

## Features

- 🔄 Real-time monitoring of Nostr notes
- 🎯 Filters out replies (only posts original notes)
- 📝 Automatic cross-posting to Bluesky
- 🖼️ Image support (automatically detects, downloads, and attaches images)
- 🧹 Smart URL removal (removes image URLs from text after uploading)
- 🛡️ Duplicate detection
- 📊 Comprehensive logging
- ⚙️ Easy configuration via .env file
- 🔧 Systemd service support for automatic startup

## Prerequisites

- Python 3.8 or higher
- A Bluesky account with an App Password
- The Nostr user's npub or public key

## Installation

1. **Clone or navigate to the project directory**

```bash
cd bluebot
```

2. **Create a virtual environment (recommended)**

```bash
python3 -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
```

3. **Install dependencies**

```bash
pip install -r requirements.txt
```

## Configuration

1. **Copy the example environment file**

```bash
cp .env.example .env
```

2. **Edit `.env` with your configuration**

```bash
nano .env  # or use your preferred editor
```

Required configuration:

```env
# Nostr Configuration
NOSTR_NPUB=npub1...
# Or use hex public key instead:
# NOSTR_PUBKEY=hex_public_key_here

# Nostr relay to monitor
NOSTR_RELAY=wss://relay.damus.io

# Bluesky Configuration
BLUESKY_USERNAME=your-handle.bsky.social
BLUESKY_APP_PASSWORD=your-app-password-here
```

### Getting Your Bluesky App Password

1. Log in to Bluesky
2. Go to Settings → App Passwords
3. Click "Add App Password"
4. Give it a name (e.g., "Nostr Cross-Poster")
5. Copy the generated password to your `.env` file

### Finding a Nostr User's npub

- Most Nostr clients display the npub in the user's profile
- npub format looks like: `npub1...` (63 characters)
- Alternatively, you can use the hex public key (64 hex characters)

## Usage

### Running the Bot

```bash
python bot.py
```

The bot will:
1. Connect to the specified Nostr relay
2. Authenticate with Bluesky
3. Start monitoring for new notes
4. Cross-post eligible notes to Bluesky

### Running in the Background

Using `screen`:
```bash
screen -S nostr-bot
python bot.py
# Press Ctrl+A, then D to detach
```

Using `tmux`:
```bash
tmux new -s nostr-bot
python bot.py
# Press Ctrl+B, then D to detach
```

Using `nohup`:
```bash
nohup python bot.py &
```

### Running as a System Service (Recommended)

For production use, it's recommended to run the bot as a systemd service. This ensures the bot:
- Starts automatically on system boot
- Restarts automatically if it crashes
- Runs in the background as a daemon
- Has proper logging through journald

#### Step 1: Create the systemd service file

An example service file is provided: `nostr-bluesky-bot.service.example`

Copy and customize it (replace `YOUR_USERNAME` with your actual username):

```bash
# Copy the example file
cp nostr-bluesky-bot.service.example nostr-bluesky-bot.service

# Edit it with your username and paths
nano nostr-bluesky-bot.service

# Install it to systemd
sudo cp nostr-bluesky-bot.service /etc/systemd/system/
```

Or create it manually:

```bash
sudo nano /etc/systemd/system/nostr-bluesky-bot.service
```

Add the following content (update paths and username):

```ini
[Unit]
Description=Nostr to Bluesky Cross-Poster Bot
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=YOUR_USERNAME
WorkingDirectory=/home/YOUR_USERNAME/Projects/bluebot
Environment="PATH=/home/YOUR_USERNAME/Projects/bluebot/venv/bin"
ExecStart=/home/YOUR_USERNAME/Projects/bluebot/venv/bin/python /home/YOUR_USERNAME/Projects/bluebot/bot.py
Restart=always
RestartSec=10
StandardOutput=journal
StandardError=journal
SyslogIdentifier=nostr-bluesky-bot

[Install]
WantedBy=multi-user.target
```

**Important**: Make sure to replace:
- `YOUR_USERNAME` with your actual Linux username (e.g., `raven`)
- Update paths if you installed the bot in a different location

#### Step 2: Reload systemd and enable the service

```bash
# Reload systemd to recognize the new service
sudo systemctl daemon-reload

# Enable the service to start on boot
sudo systemctl enable nostr-bluesky-bot.service

# Start the service now
sudo systemctl start nostr-bluesky-bot.service
```

#### Step 3: Check the service status

```bash
# Check if the service is running
sudo systemctl status nostr-bluesky-bot.service

# View recent logs
sudo journalctl -u nostr-bluesky-bot.service -n 50 -f
```

#### Managing the service

```bash
# Start the bot
sudo systemctl start nostr-bluesky-bot.service

# Stop the bot
sudo systemctl stop nostr-bluesky-bot.service

# Restart the bot
sudo systemctl restart nostr-bluesky-bot.service

# Disable auto-start on boot
sudo systemctl disable nostr-bluesky-bot.service

# View all logs
sudo journalctl -u nostr-bluesky-bot.service

# View logs from today
sudo journalctl -u nostr-bluesky-bot.service --since today

# Follow logs in real-time
sudo journalctl -u nostr-bluesky-bot.service -f
```

#### Troubleshooting the service

If the service fails to start:

1. **Check service status**:
   ```bash
   sudo systemctl status nostr-bluesky-bot.service
   ```

2. **View error logs**:
   ```bash
   sudo journalctl -u nostr-bluesky-bot.service -n 100 --no-pager
   ```

3. **Verify paths**: Make sure all paths in the service file are correct
   ```bash
   # Check if virtual environment exists
   ls -la /home/YOUR_USERNAME/Projects/bluebot/venv/bin/python

   # Check if bot.py exists
   ls -la /home/YOUR_USERNAME/Projects/bluebot/bot.py
   ```

4. **Check permissions**: Ensure your user has read access to the bot directory
   ```bash
   ls -la /home/YOUR_USERNAME/Projects/bluebot/
   ```

5. **Test manually**: Try running the bot manually to see if there are any errors
   ```bash
   cd /home/YOUR_USERNAME/Projects/bluebot
   source venv/bin/activate
   python bot.py
   ```

### Stopping the Bot

If running in foreground:
- Press `Ctrl+C`

If running in background:
- Find the process: `ps aux | grep bot.py`
- Kill it: `kill <PID>`

## Logs

The bot creates two log outputs:
- **Console output**: Real-time logs displayed in terminal
- **bot.log**: Persistent log file with detailed information

## How It Works

1. **Monitoring**: The bot subscribes to kind 1 notes from the specified Nostr user
2. **Filtering**:
   - Skips replies (notes with 'e' tags referencing other events)
   - Skips empty notes
   - Prevents duplicate posts
3. **Image Processing**:
   - Detects image URLs in note content (supports .jpg, .jpeg, .png, .gif, .webp)
   - Downloads and validates images (max 10MB per image)
   - Uploads images to Bluesky (up to 4 images per post)
   - Removes image URLs from the text after successful upload
4. **Cross-posting**: Posts the note content to Bluesky with attached images
5. **Logging**: Records all actions for debugging and monitoring

## Troubleshooting

### Bot won't connect to Nostr relay

- Try a different relay (common ones: `wss://relay.damus.io`, `wss://nos.lol`, `wss://relay.nostr.band`)
- Check your internet connection
- Verify the relay URL is correct

### Bluesky authentication fails

- Verify your username includes the domain (e.g., `user.bsky.social`)
- Ensure you're using an App Password, not your main account password
- Check for typos in your credentials

### No notes are being cross-posted

- The bot only monitors notes created AFTER it starts
- Verify the npub/public key is correct
- Check that the user is posting to the relay you're monitoring
- Review the logs for any error messages

### Notes are posted multiple times

- This shouldn't happen due to duplicate detection
- If it does, check the logs and consider restarting the bot

### Images aren't being uploaded

- Check the logs for download/upload errors
- Ensure the image URL is accessible (try opening it in a browser)
- Verify the image size is under 10MB
- Supported formats: .jpg, .jpeg, .png, .gif, .webp
- The bot supports up to 4 images per post
- If an image fails to upload, its URL will remain in the text

## Customization

You can modify `bot.py` to:
- Add custom formatting to cross-posted notes
- Include source attribution (e.g., "Posted from Nostr")
- Customize image alt text
- Add rate limiting
- Support multiple relays
- Add video support (currently only images are supported)

## Security Notes

- Keep your `.env` file secure and never commit it to version control
- Use App Passwords instead of your main Bluesky password
- The bot requires network access to connect to Nostr relays and Bluesky

## License

This project is provided as-is for personal use.

## Contributing

Feel free to submit issues or pull requests for improvements!
