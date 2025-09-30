#!/bin/bash
while true; do
  echo "$(date): Queue length: $(docker-compose exec redis redis-cli llen summarization 2>/dev/null)"
  echo "$(date): Web logs tail:"
  tail -5 web_monitor.txt 2>/dev/null | grep -E "(summar|Summar|queue|Queue)" || echo "No summarization activity in logs"
  echo "---"
  sleep 2
done
