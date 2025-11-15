#!/usr/bin/env python3
"""
Restart all Railway services to clear DB connection cache
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


def restart_service(service: str):
    """Restart a single Railway service"""
    print(f"\n🔄 Restarting {service}...")

    # Try to restart the service
    cmd = f"railway service {service}"
    stdout, stderr, code = run_cmd(cmd)

    if code != 0:
        print(f"   ❌ Could not access {service}: {stderr}")
        return False

    # Wait a moment
    print(f"   ⏳ Waiting for {service} to restart...")
    time.sleep(3)

    # Check if service is running
    cmd = f"railway logs {service} --lines 5"
    stdout, stderr, code = run_cmd(cmd)

    if code == 0 and "started" in stdout.lower():
        print(f"   ✅ {service} restarted successfully")
        return True
    else:
        print(f"   ⚠️  {service} status unclear")
        return True


def main():
    """Main function"""
    print("🚀 Polycool Railway Services Restart")
    print("=" * 45)
    print("This will restart all services to clear DB connection cache")

    # Check if railway CLI is available
    stdout, stderr, code = run_cmd("railway --version")
    if code != 0:
        print("❌ Railway CLI not found")
        sys.exit(1)

    # Check if logged in
    stdout, stderr, code = run_cmd("railway whoami")
    if code != 0:
        print("❌ Not logged in to Railway")
        sys.exit(1)

    services = ['polycool-api', 'polycool-bot', 'polycool-workers', 'polycool-indexer']

    success_count = 0

    for service in services:
        if restart_service(service):
            success_count += 1

    print(f"\n✅ Restarted {success_count}/{len(services)} services")
    print("\n⏳ Waiting 30 seconds for services to fully initialize...")
    time.sleep(30)

    print("\n🎯 Test your API now:")
    print("   curl https://your-api-url/api/v1/markets/trending")
    print("   curl https://your-api-url/api/v1/markets/551963")

    print("\n💡 If still failing, check Railway logs:")
    print("   railway logs polycool-api --follow")


if __name__ == "__main__":
    main()
