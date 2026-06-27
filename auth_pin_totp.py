#!/usr/bin/env python3.11
"""
DhanHQ Authentication - PIN + TOTP Flow (Method 2)
Supports both manual TOTP entry and automatic TOTP generation from secret.

Requires: Python 3.11+, dhanhq==2.2.0, pyotp
"""
import os
import sys
import pyotp
from dhanhq import DhanLogin


def get_totp_from_secret(totp_secret: str) -> str:
    """Generate current TOTP code from base32 secret."""
    return pyotp.TOTP(totp_secret).now()


def main():
    client_id = os.environ.get("DHAN_CLIENT_ID")
    if not client_id:
        client_id = input("Enter Dhan Client ID: ").strip()
    if not client_id:
        print("Client ID is required")
        sys.exit(1)

    pin = os.environ.get("DHAN_PIN")
    if not pin:
        pin = input("Enter 6-digit PIN: ").strip()
    if not pin or len(pin) != 6 or not pin.isdigit():
        print("Valid 6-digit PIN is required")
        sys.exit(1)

    # TOTP: either from secret (auto) or manual entry
    totp_secret = os.environ.get("DHAN_TOTP_SECRET")
    if totp_secret:
        # Auto-generate TOTP from secret
        totp = get_totp_from_secret(totp_secret)
        print(f"Auto-generated TOTP: {totp}")
    else:
        # Manual entry fallback
        totp = os.environ.get("DHAN_TOTP")
        if not totp:
            totp = input("Enter TOTP (from authenticator app): ").strip()
        if not totp or len(totp) != 6 or not totp.isdigit():
            print("Valid 6-digit TOTP is required")
            sys.exit(1)

    print("\nGenerating access token...")
    dhan_login = DhanLogin(client_id)

    try:
        token_data = dhan_login.generate_token(pin, totp)
        access_token = token_data['access_token']
        print(f"\n✓ Access token generated successfully!")
        print(f"\naccess_token = {access_token}")
        print(f"\nSet this in your environment:")
        print(f'  export DHAN_ACCESS_TOKEN="{access_token}"')
        print(f"\nToken expires in 24 hours. To renew:")
        print(f'  python3.11 -c "from dhanhq import DhanLogin; DhanLogin(\"{client_id}\").renew_token(\"<token>\")"')
        return access_token
    except Exception as e:
        print(f"\n✗ Failed to generate token: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()