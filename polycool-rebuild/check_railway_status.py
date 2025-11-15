#!/usr/bin/env python3
"""
Check Railway services status and variables
"""
import subprocess
import sys


def run_cmd(cmd: str) -> tuple[str, str, int]:
    """Run command and return output"""
    try:
        result = subprocess.run(cmd, shell=True, capture_output=True, text=True)
        return result.stdout.strip(), result.stderr.strip(), result.returncode
    except Exception as e:
        return "", str(e), 1


def check_service_variables(service: str):
    """Check DATABASE_URL for a service"""
    print(f"\n🔍 Checking {service}...")
    
    # Get DATABASE_URL
    cmd = f"railway variables --service {service} --format json | grep DATABASE_URL"
    stdout, stderr, code = run_cmd(cmd)
    
    if code == 0 and stdout:
        print(f"   ✅ {service}: Variables accessible")
        # Check if contains new password
        if "ClDSK0N5IedorZes" in stdout:
            print(f"   ✅ {service}: Has NEW password")
        elif "burnzeboats2025" in stdout:
            print(f"   ❌ {service}: Has OLD password!")
        else:
            print(f"   ⚠️  {service}: Password not visible in output")
    else:
        print(f"   ❌ {service}: Cannot access variables ({stderr[:100]}...)")


def main():
    """Main function"""
    print("🔍 Checking Railway Services Status")
    print("=" * 40)
    
    services = ['polycool-api', 'polycool-bot', 'polycool-workers', 'polycool-indexer']
    
    for service in services:
        check_service_variables(service)
    
    print()
    print("💡 Actions needed:")
    print("1. If any service has OLD password → Re-run fix_railway_password.py")
    print("2. Force restart all services via Railway dashboard")
    print("3. Check logs after restart")


if __name__ == "__main__":
    main()
