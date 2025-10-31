# Environment Variables Setup

## Overview

The AlgoStrangle system requires API credentials and notification tokens to operate. For security, these sensitive values are loaded from environment variables rather than being hard-coded in the repository.

## Required Environment Variables

### 1. Kite Connect API (For Live/Paper Trading)

```bash
export KITE_API_KEY="your_api_key_here"
export KITE_API_SECRET="your_api_secret_here"
```

**Where to get these:**
1. Log in to [Kite Connect Developer Console](https://developers.kite.trade/)
2. Create a new app or use an existing one
3. Copy the API Key and API Secret

### 2. Telegram Notifications (Optional)

```bash
export TELEGRAM_BOT_TOKEN="your_bot_token_here"
export TELEGRAM_CHAT_ID="your_chat_id_here"
```

**Where to get these:**
1. Create a bot with [@BotFather](https://t.me/botfather) on Telegram
2. Copy the bot token provided
3. Get your chat ID by messaging [@userinfobot](https://t.me/userinfobot)

**Note:** If Telegram variables are not set, the system will still work but notifications will be disabled.

## Setup Methods

### Method 1: Export in Terminal (Temporary)

```bash
# Set for current terminal session
export KITE_API_KEY="qdss2yswc2iuen3j"
export KITE_API_SECRET="q9cfy774cgt8z0exp0tlat4rntj7huqs"
export TELEGRAM_BOT_TOKEN="7668822476:AAEeSzWdt7DgzOs3Fsbz5_oZpPL8xoUpLH8"
export TELEGRAM_CHAT_ID="7745188241"

# Run the system
python run.py
```

**Pros:** Quick for testing  
**Cons:** Variables lost when terminal closes

### Method 2: .bashrc / .zshrc (Permanent for User)

Add to your shell configuration file (`~/.bashrc` or `~/.zshrc`):

```bash
# AlgoStrangle Environment Variables
export KITE_API_KEY="your_api_key_here"
export KITE_API_SECRET="your_api_secret_here"
export TELEGRAM_BOT_TOKEN="your_bot_token_here"
export TELEGRAM_CHAT_ID="your_chat_id_here"
```

Then reload:
```bash
source ~/.bashrc  # or source ~/.zshrc
```

**Pros:** Available in all terminal sessions  
**Cons:** Stored in plain text in home directory

### Method 3: .env File with python-dotenv (Recommended)

1. **Install python-dotenv:**
   ```bash
   pip install python-dotenv
   ```

2. **Create `.env` file in project root:**
   ```bash
   # .env file (DO NOT COMMIT THIS FILE)
   KITE_API_KEY=your_api_key_here
   KITE_API_SECRET=your_api_secret_here
   TELEGRAM_BOT_TOKEN=your_bot_token_here
   TELEGRAM_CHAT_ID=your_chat_id_here
   ```

3. **Update run.py to load .env (optional):**
   Add at the top of `run.py`:
   ```python
   from dotenv import load_dotenv
   load_dotenv()  # Load .env file
   ```

4. **Ensure .env is in .gitignore:**
   ```bash
   echo ".env" >> .gitignore
   ```

**Pros:** 
- Project-specific configuration
- Easy to switch between environments
- Can be backed up securely

**Cons:** 
- Requires additional dependency
- File must be kept secure

### Method 4: System Environment (Production)

For production servers, set system-wide environment variables:

**Linux/MacOS:**
```bash
sudo nano /etc/environment
```

Add lines:
```
KITE_API_KEY="your_api_key_here"
KITE_API_SECRET="your_api_secret_here"
```

**Windows:**
- Right-click "This PC" → Properties → Advanced System Settings
- Environment Variables → New (System Variables)
- Add each variable

## Verification

To verify environment variables are set:

```bash
# Check if variables are set
echo $KITE_API_KEY
echo $KITE_API_SECRET
echo $TELEGRAM_BOT_TOKEN
echo $TELEGRAM_CHAT_ID
```

Or run Python:
```python
import os
print("API Key:", os.getenv('KITE_API_KEY', 'NOT SET'))
print("API Secret:", os.getenv('KITE_API_SECRET', 'NOT SET'))
print("Telegram Bot Token:", os.getenv('TELEGRAM_BOT_TOKEN', 'NOT SET'))
print("Telegram Chat ID:", os.getenv('TELEGRAM_CHAT_ID', 'NOT SET'))
```

## Backtest Mode

**Good news:** Backtest mode does NOT require API credentials to be set. The system will show warnings but will function normally using cached historical data.

```bash
# Backtest without API credentials
python run.py
# Select: 3 (Backtest)
```

## Security Best Practices

### ✅ DO:
- Use .env files for local development
- Add .env to .gitignore
- Use environment variables in production
- Rotate API keys periodically
- Use separate credentials for development vs. production

### ❌ DON'T:
- Commit .env files to git
- Hard-code credentials in source code
- Share credentials in chat/email
- Use production credentials for testing
- Store credentials in public repositories

## Troubleshooting

### Warning: "KITE_API_KEY or KITE_API_SECRET not set"

**Solution:** Set the environment variables using one of the methods above.

**If you're running backtest:** This warning is harmless - backtests work without credentials.

**If you're running live/paper trading:** You must set credentials or the system will fail to authenticate.

### Telegram Notifications Not Working

1. **Check variables are set:**
   ```bash
   echo $TELEGRAM_BOT_TOKEN
   echo $TELEGRAM_CHAT_ID
   ```

2. **Verify bot token is valid:**
   - Message your bot on Telegram
   - It should respond if active

3. **Verify chat ID:**
   - Should be a numeric ID (e.g., "7745188241")
   - Get from @userinfobot

4. **Check system logs:**
   ```bash
   tail -f logs/main_logs/strangle_trading_*.log | grep -i telegram
   ```

### Environment Variables Not Loading

**If using .env file:**
1. Confirm python-dotenv is installed: `pip list | grep dotenv`
2. Confirm load_dotenv() is called in run.py
3. Confirm .env file is in same directory as run.py
4. Check file permissions: `ls -la .env`

**If using shell exports:**
1. Confirm exports are in correct file (~/.bashrc or ~/.zshrc)
2. Source the file: `source ~/.bashrc`
3. Open new terminal and verify: `echo $KITE_API_KEY`

## Example .env File Template

Create a file named `.env` in the project root:

```env
# Kite Connect API Credentials
# Get from: https://developers.kite.trade/
KITE_API_KEY=your_api_key_here
KITE_API_SECRET=your_api_secret_here

# Telegram Notifications (Optional)
# Bot Token from @BotFather
# Chat ID from @userinfobot
TELEGRAM_BOT_TOKEN=your_bot_token_here
TELEGRAM_CHAT_ID=your_chat_id_here

# Optional: Override other config values
# CAPITAL=500000
# DAILY_MAX_LOSS_PCT=0.02
```

Then ensure it's in `.gitignore`:
```bash
# Check if .env is already in .gitignore
grep -q "^\.env$" .gitignore || echo ".env" >> .gitignore
```

## Migration from Hard-Coded Credentials

If you have an older version of the code with hard-coded credentials:

1. **Extract current values:**
   ```python
   # From old strangle/config.py
   API_KEY = "qdss2yswc2iuen3j"  # Copy this
   API_SECRET = "q9cfy774cgt8z0exp0tlat4rntj7huqs"  # Copy this
   ```

2. **Create .env file:**
   ```bash
   cat > .env << EOF
   KITE_API_KEY=qdss2yswc2iuen3j
   KITE_API_SECRET=q9cfy774cgt8z0exp0tlat4rntj7huqs
   TELEGRAM_BOT_TOKEN=7668822476:AAEeSzWdt7DgzOs3Fsbz5_oZpPL8xoUpLH8
   TELEGRAM_CHAT_ID=7745188241
   EOF
   ```

3. **Verify new code loads from environment:**
   ```bash
   python -c "from strangle.config import Config; print(f'API_KEY: {Config.API_KEY[:10]}...')"
   ```

4. **Update .gitignore:**
   ```bash
   echo ".env" >> .gitignore
   git add .gitignore
   git commit -m "Add .env to gitignore"
   ```

## Support

If you encounter issues with environment variable setup:
1. Check the troubleshooting section above
2. Review logs in `logs/main_logs/`
3. Open an issue on GitHub with error details
