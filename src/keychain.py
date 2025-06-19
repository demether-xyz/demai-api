"""iCloud Keychain utility functions for managing secrets"""

import os
import subprocess
import sys
from typing import Optional, Tuple

def get_secret(service: str, account: str) -> Optional[str]:
    """Get a secret from iCloud Keychain."""
    try:
        result = subprocess.run(
            ["security", "-i", "find-generic-password", "-s", service, "-a", account, "-w"],
            capture_output=True,
            text=True,
            check=True
        )
        return result.stdout.strip()
    except subprocess.CalledProcessError as e:
        print(f"Error accessing iCloud Keychain for {account}: {e}", file=sys.stderr)
        return None

def delete_secret(service: str, account: str) -> bool:
    """Delete a secret from the iCloud Keychain."""
    try:
        subprocess.run(
            ["security", "-i", "delete-generic-password", "-s", service, "-a", account],
            capture_output=True,
            check=True
        )
        return True
    except subprocess.CalledProcessError as e:
        # If secret doesn't exist, that's fine
        if "The specified item could not be found" in str(e.stderr):
            return True
        print(f"Error deleting iCloud Keychain secret for {account}: {e}", file=sys.stderr)
        return False

def add_secret(service: str, account: str, secret: str) -> bool:
    """Add or update a secret in the iCloud Keychain."""
    try:
        # Delete existing password if it exists (ignore errors)
        delete_secret(service, account)
        
        # Add new password to iCloud Keychain
        subprocess.run(
            ["security", "-i", "add-generic-password", "-s", service, "-a", account, "-w", secret],
            capture_output=True,
            text=True,
            check=True
        )
        return True
    except subprocess.CalledProcessError as e:
        print(f"Error setting iCloud Keychain secret for {account}: {e}", file=sys.stderr)
        return False

def load_secrets(secrets: list[Tuple[str, str, Optional[str]]]) -> bool:
    """Load secrets from iCloud Keychain into environment variables."""
    success = True
    
    for service, account, env_var in secrets:
        if env_var is None:
            env_var = account
            
        secret = get_secret(service, account)
        if secret:
            os.environ[env_var] = secret
        else:
            success = False
            
    return success

if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description="Manage iCloud Keychain secrets")
    parser.add_argument("action", choices=["get", "set", "delete"], help="Action to perform")
    parser.add_argument("service", help="Keychain service name")
    parser.add_argument("account", help="Account/key name")
    parser.add_argument("secret", nargs="?", help="Secret value (only for 'set' action)")
    
    args = parser.parse_args()
    
    if args.action == "get":
        secret = get_secret(args.service, args.account)
        if secret:
            print(secret)
            sys.exit(0)
        sys.exit(1)
    
    elif args.action == "set":
        if not args.secret:
            parser.error("'set' action requires a secret value")
        if add_secret(args.service, args.account, args.secret):
            print(f"Successfully added secret {args.account} to iCloud Keychain")
            sys.exit(0)
        sys.exit(1)
    
    elif args.action == "delete":
        if delete_secret(args.service, args.account):
            print(f"Successfully deleted secret {args.account} from iCloud Keychain")
            sys.exit(0)
        sys.exit(1) 