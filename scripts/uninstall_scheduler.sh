#!/bin/bash
launchctl unload ~/Library/LaunchAgents/com.rental.ledger.sync.plist
rm ~/Library/LaunchAgents/com.rental.ledger.sync.plist
echo "✅ Scheduler uninstalled"
