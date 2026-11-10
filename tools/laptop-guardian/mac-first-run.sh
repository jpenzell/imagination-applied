#!/bin/bash
# First run of guardian on a real Mac: tests, doctor, status, dry-run watch, simulate, disk
# census, Chrome census. Everything here is read-only / dry-run. Output is also saved to a
# file you can paste into a Claude or Codex session for review.
#
#   bash mac-first-run.sh              # look only
#   bash mac-first-run.sh --install    # then also: autopilot on, test-notify, agent checks
set -u
cd "$(dirname "$0")"
OUT=~/Library/Logs/guardian/first-run-$(date +%Y%m%d-%H%M).txt
mkdir -p ~/Library/Logs/guardian
exec > >(tee "$OUT") 2>&1
echo "guardian first run on $(hostname -s), $(date), $(sw_vers -productVersion 2>/dev/null) $(uname -m)"
echo "python3: $(command -v python3) $(python3 --version 2>&1)"
run() { echo; echo "### $*"; "$@"; echo "### exit $?"; }

run python3 test_guardian.py
run python3 test_scratch.py
run python3 test_archive.py
run python3 guardian.py doctor
run python3 guardian.py status -n 20
run python3 guardian.py watch --once --dry-run
run python3 guardian.py watch --once --dry-run --simulate level=4,free=3,disk=9
run python3 guardian.py scratch
run python3 guardian.py chrome
echo; echo "### raw readings (compare with Activity Monitor and df -h)"
sysctl -n kern.memorystatus_vm_pressure_level kern.memorystatus_level vm.swapusage vm.loadavg hw.memsize
vm_stat | head -3; vm_stat | grep compressor
echo; echo "### Activity Monitor's Memory column (top MEM = physical footprint) for the biggest processes"
top -l 1 -o mem -stats pid,mem,cmprs,command 2>/dev/null | sed -n '/^PID/,$p' | head -16
pmset -g therm
df -h /
tmutil listlocalsnapshots / 2>&1 | head -5
echo; echo "### AI data folders present on this Mac"
ls -d ~/Library/Application\ Support/Claude ~/Library/Application\ Support/Claude/* \
      ~/Library/Application\ Support/com.openai.* ~/Library/Containers/com.openai.* \
      ~/Library/Caches/com.openai.* ~/Library/Caches/com.anthropic.* ~/.codex ~/.codex/* ~/.claude ~/.claude/* 2>/dev/null
echo; echo "### parent chain of every claude / codex / node / Python process (for classify())"
ps -axo pid=,ppid=,comm= | grep -iE 'claude|codex|node|python|chatgpt|chrome' | grep -v grep | head -120

if [ "${1:-}" = "--install" ]; then
  run python3 guardian.py autopilot on
  run python3 guardian.py test-notify
  echo "(a macOS notification should have appeared; if not: System Settings > Notifications > Script Editor)"
  sleep 5
  run launchctl list local.guardian
  run python3 guardian.py autopilot status
  run tail -5 ~/Library/Logs/guardian/events.jsonl
  echo; echo "### in two minutes, this should be growing:  wc -l ~/Library/Logs/guardian/samples.tsv"
  echo "### overhead: ps -o %cpu=,rss=,etime= -p \$(pgrep -f 'guardian.py watch')   (expect <1% cpu, <60MB rss)"
fi
echo; echo "saved to $OUT"
