#!/usr/bin/env python3
"""Nexus Post-Install Patch — entfernt Hermes-spezifische Nachrichten."""
import os
import sys

def patch_home_channel():
    run_py = '/opt/hermes/gateway/run.py'
    if not os.path.exists(run_py):
        print("⚠️  run.py not found")
        return False

    with open(run_py, 'r') as f:
        content = f.read()

    if 'NEXUS_PATCHED' in content:
        print("✅ Already patched")
        return True

    old = '📬 No home channel is set for'
    if old in content:
        content = content.replace(
            '                    f"📬 No home channel is set for {platform_name.title()}. "\n'
            '                    f"A home channel is where Hermes delivers cron job results "',
            '                    # NEXUS_PATCHED\n'
            '                    pass'
        )
        with open(run_py, 'w') as f:
            f.write(content)
        print("✅ Home channel message patched")
        return True
    else:
        print("⚠️  Pattern not found")
        return False

if __name__ == '__main__':
    success = patch_home_channel()
    sys.exit(0 if success else 1)
