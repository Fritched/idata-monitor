cat > ~/idata-monitor/README.md << 'EOF'
# iDATA Visa Appointment Monitor
An AI-powered monitoring tool that watches the iDATA visa appointment portal and sends instant alerts when a slot becomes available.
## What it does
- Monitors Gmail inbox for appointment emails from iDATA in real time
- Uses Claude AI (Anthropic) to analyze and confirm slot availability
- Sends instant alerts via Telegram and email the moment anything changes
- Runs automatically in the background 24/7
## Why I built this
Getting a Schengen visa appointment through iDATA in Turkey is extremely competitive. Slots are assigned randomly and the confirmation window is only 48 hours. Missing the email means going back to the end of the queue. I built this tool to make sure I never miss that window.
## Tech stack
- Python 3.11
- Playwright (browser automation)
- Anthropic Claude API (AI analysis)
- Gmail IMAP (inbox monitoring)
- Telegram Bot API (instant alerts)
## How it works
1. Every few minutes, checks Gmail for unread emails from iDATA
2. If an email is found, immediately fires a Telegram and email alert
3. Claude AI confirms the content before alerting to avoid false positives
EOF
