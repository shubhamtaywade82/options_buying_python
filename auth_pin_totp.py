#!/usr/bin/env python3.11
"""
DhanHQ Authentication - PIN + TOTP Flow (Method 2)
Auto-generates TOTP from secret, fetches access token, and writes to .env

Requires: Python 3.11+, dhanhq==2.2.0, pyotp, python-dotenv
"""
import os
import sys
from pathlib import Path
from dotenv import load_dotenv, set_key
import pyotp
from dhanhq import DhanLogin


# Path to .env file
ENV_FILE = Path(__file__).parent / ".env"

# Load existing .env
load_dotenv(ENV_FILE)


def get_totp_from_secret(totp_secret: str) -> str:
    """Generate current TOTP code from base32 secret."""
    return pyotp.TOTP(totp_secret).now()


def write_token_to_env(access_token: str) -> None:
    """Write access token to .env file."""
    # Ensure .env exists
    if not ENV_FILE.exists():
        ENV_FILE.write_text("")
    
    # Write/overwrite DHAN_ACCESS_TOKEN
    set_key(str(ENV_FILE), "DHAN_ACCESS_TOKEN", access_token)
    print(f"\n✓ Written DHAN_ACCESS_TOKEN to {ENV_FILE}")


def main():
    client_id = os.environ.get("DHAN_CLIENT_ID")
    if not client_id:
        client_id = input("Enter Dhan Client ID: ").strip()
    if not client_id:
        print("Client ID is required (set DHAN_CLIENT_ID in .env)")
        sys.exit(1)

    pin = os.environ.get("DHAN_PIN")
    if not pin:
        pin = input("Enter 6-digit PIN: ").strip()
    if not pin or len(pin) != 6 or not pin.isdigit():
        print("Valid 6-digit PIN is required (set DHAN_PIN in .env)")
        sys.exit(1)

    # TOTP: auto-generate from secret
    totp_secret = os.environ.get("DHAN_TOTP_SECRET")
    if not totp_secret:
        print("DHAN_TOTP_SECRET not set in .env")
        print("Get base32 secret from Dhan 2FA setup and add to .env")
        sys.exit(1)
    
    totp = get_totp_from_secret(totp_secret)
    print(f"Auto-generated TOTP: {totp}")

    print("\nGenerating access token...")
    dhan_login = DhanLogin(client_id)

    try:
        token_data = dhan_login.generate_token(pin, totp)
        # API returns 'accessToken' (camelCase)
        access_token = token_data.get('accessToken') or token_data.get('access_token')
        if not access_token:
            raise KeyError(f"No access_token in response: {token_data}")
        print(f"\n✓ Access token generated successfully!")
        print(f"access_token = {access_token}")

        # Auto-write to .env
        write_token_to_env(access_token)

        print(f"\nToken expires in 24 hours. To renew:")
        print(f'  python auth_pin_totp.py')
        return access_token
    except Exception as e:
        print(f"\n✗ Failed to generate token: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()