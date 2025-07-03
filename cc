#!/bin/bash

LOG_DIR="/var/log/audit"
DRY_RUN=false    # Set to true to simulate deletions without actually removing files

# Get disk usage percentage for the partition
USAGE=$(df "$LOG_DIR" | awk 'NR==2 {print $5}' | tr -d '%')

# Today's date marker to preserve today's logs
TODAY=$(date +%Y-%m-%d)

# Determine retention period based on disk usage
if [ "$USAGE" -ge 90 ]; then
    echo "Disk usage is ${USAGE}%. Deleting logs older than 3 days (except today's)."
    RETENTION=3
else
    echo "Disk usage is ${USAGE}%. Deleting logs older than 15 days (except today's)."
    RETENTION=15
fi

# Find logs older than retention period and not modified today
FILES=$(find "$LOG_DIR" -type f -name "*.log" -mtime +"$RETENTION" ! -newermt "$TODAY")

if [ "$DRY_RUN" = true ]; then
    echo "Dry run enabled. The following files would be deleted:"
    echo "$FILES"
else
    echo "Deleting files:"
    echo "$FILES"
    echo "$FILES" | xargs -r rm -f
fi
