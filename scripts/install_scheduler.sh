#!/bin/bash
mkdir -p /Users/manjax/Documents/Code/AI/rental-ledger-sync/logs
cp /Users/manjax/Documents/Code/AI/rental-ledger-sync/com.rental.ledger.sync.plist ~/Library/LaunchAgents/
launchctl load ~/Library/LaunchAgents/com.rental.ledger.sync.plist
echo "✅ Scheduler installed - sync will run daily at 7:00 AM"
echo "   Logs: /Users/manjax/Documents/Code/AI/rental-ledger-sync/logs/"
