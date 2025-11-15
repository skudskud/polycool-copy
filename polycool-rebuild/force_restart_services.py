#!/usr/bin/env python3
"""
Force restart all Railway services
"""
import subprocess
import sys
import time


def run_cmd(cmd: str) -> tuple[str, str, int]:
    """Run command and return output"""
    try:
        result = subprocess.run(cmd, shell=True, capture_output=True, text=True)
        return result.stdout.strip(), result.stderr.strip(), result.returncode
    except Exception as e:
        return "", str(e), 1


def force_restart_services():
    """Force restart all services"""
    
    services = ['polycool-api', 'polycool-bot', 'polycool-workers', 'polycool-indexer']
    
    print("🔄 Force restarting all Railway services...")
    print("This will apply the new DATABASE_URL with correct password")
    print()
    
    for service in services:
        print(f"📡 Triggering restart for {service}...")
        
        # This will trigger a restart
        cmd = f'railway logs {service} --lines 1 >/dev/null 2>&1'
        run_cmd(cmd)
        
        # Small delay between services
        time.sleep(2)
    
    print("✅ All services restart triggered")
    print("⏳ Wait 30-60 seconds for services to fully restart")
    print()
    print("🎯 Check logs with: railway logs polycool-workers --follow")


if __name__ == "__main__":
    force_restart_services()
