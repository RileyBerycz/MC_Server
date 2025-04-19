#!/usr/bin/env python3

import json
import os
import subprocess
import re
import sys
import socket
import argparse
from colorama import init, Fore, Style

# Initialize colorama for cross-platform colored output
init()

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

def lookup_dns_cname(domain):
    """Try multiple methods to look up a CNAME record."""
    # Method 1: Using dig
    try:
        result = subprocess.check_output(["dig", "CNAME", domain, "+short"], universal_newlines=True).strip()
        if result and "cfargotunnel.com" in result:
            return result.split(".")[0]  # Extract tunnel ID
    except (subprocess.SubprocessError, FileNotFoundError):
        pass
    
    # Method 2: Using nslookup
    try:
        result = subprocess.check_output(["nslookup", "-type=CNAME", domain], universal_newlines=True)
        match = re.search(r'canonical name = ([0-9a-f-]+)\.cfargotunnel\.com', result)
        if match:
            return match.group(1)
    except (subprocess.SubprocessError, FileNotFoundError):
        pass
    
    # Method 3: Using host
    try:
        result = subprocess.check_output(["host", "-t", "CNAME", domain], universal_newlines=True)
        match = re.search(r'is an alias for ([0-9a-f-]+)\.cfargotunnel\.com', result)
        if match:
            return match.group(1)
    except (subprocess.SubprocessError, FileNotFoundError):
        pass
    
    # Method 4: Windows-specific nslookup syntax
    try:
        result = subprocess.check_output(["nslookup", "-type=cname", domain], universal_newlines=True)
        match = re.search(r'canonical name = ([0-9a-f-]+)\.cfargotunnel\.com', result)
        if match:
            return match.group(1)
    except (subprocess.SubprocessError, FileNotFoundError):
        pass
    
    # If all methods fail, return None
    return None

def validate_tunnels(fix=False, auto_fix=False, verbose=False, dry_run=False):
    """Validate tunnel mappings against DNS records."""
    tunnel_map_path = os.path.join(BASE_DIR, "tunnel_id_map.json")
    
    if not os.path.exists(tunnel_map_path):
        print(f"{Fore.RED}Error: tunnel_id_map.json not found at {tunnel_map_path}{Style.RESET_ALL}")
        return False
    
    try:
        with open(tunnel_map_path, "r") as f:
            tunnel_map = json.load(f)
    except json.JSONDecodeError:
        print(f"{Fore.RED}Error: tunnel_id_map.json is not valid JSON{Style.RESET_ALL}")
        return False
    
    print(f"{Fore.CYAN}Checking {len(tunnel_map)} tunnel mappings against DNS records...{Style.RESET_ALL}")
    
    mismatches = []
    correct = []
    errors = []
    
    for fqdn, tunnel_id in tunnel_map.items():
        if verbose:
            print(f"Checking {fqdn}...", end="", flush=True)
        
        dns_tunnel_id = lookup_dns_cname(fqdn)
        
        if dns_tunnel_id is None:
            print(f"{Fore.YELLOW}⚠️ Warning: Could not resolve CNAME for {fqdn}{Style.RESET_ALL}")
            errors.append(fqdn)
            continue
            
        if dns_tunnel_id != tunnel_id:
            print(f"{Fore.RED}❌ Mismatch: {fqdn}{Style.RESET_ALL}")
            print(f"  Map value: {tunnel_id}")
            print(f"  DNS value: {dns_tunnel_id}")
            mismatches.append({
                "fqdn": fqdn,
                "map_tunnel_id": tunnel_id,
                "dns_tunnel_id": dns_tunnel_id
            })
        else:
            if verbose:
                print(f"{Fore.GREEN}✅ Match{Style.RESET_ALL}")
            correct.append(fqdn)
    
    # Print summary
    print("\n" + "="*70)
    print(f"{Fore.CYAN}VALIDATION SUMMARY{Style.RESET_ALL}")
    print("="*70)
    print(f"Total mappings checked: {len(tunnel_map)}")
    print(f"Correct mappings: {Fore.GREEN}{len(correct)}{Style.RESET_ALL}")
    print(f"Mismatched mappings: {Fore.RED if mismatches else Fore.GREEN}{len(mismatches)}{Style.RESET_ALL}")
    print(f"Lookup errors: {Fore.YELLOW if errors else Fore.GREEN}{len(errors)}{Style.RESET_ALL}")
    
    # If there are mismatches, provide detailed report
    if mismatches:
        print("\n" + "="*70)
        print(f"{Fore.RED}MISMATCHED TUNNELS{Style.RESET_ALL}")
        print("="*70)
        for mismatch in mismatches:
            print(f"FQDN: {mismatch['fqdn']}")
            print(f"  Map value: {mismatch['map_tunnel_id']}")
            print(f"  DNS value: {mismatch['dns_tunnel_id']}")
            print("  Options to fix:")
            print(f"  1. Update DNS: Set CNAME to {mismatch['map_tunnel_id']}.cfargotunnel.com")
            print(f"  2. Update map: Change tunnel ID in tunnel_id_map.json to {mismatch['dns_tunnel_id']}")
            print()
        
        # If auto-fix option is enabled, update without asking
        if auto_fix:
            if dry_run:
                print(f"{Fore.YELLOW}DRY RUN: Would automatically update tunnel_id_map.json with these changes:{Style.RESET_ALL}")
                for mismatch in mismatches:
                    print(f"  {mismatch['fqdn']}: {mismatch['map_tunnel_id']} → {mismatch['dns_tunnel_id']}")
                return len(mismatches) == 0
            
            print(f"{Fore.YELLOW}Auto-fixing all {len(mismatches)} mismatches to match DNS records...{Style.RESET_ALL}")
            for mismatch in mismatches:
                tunnel_map[mismatch['fqdn']] = mismatch['dns_tunnel_id']
            
            # Backup the original file
            backup_path = tunnel_map_path + ".backup"
            try:
                with open(backup_path, "w") as f:
                    json.dump(tunnel_map, f, indent=2)
                print(f"{Fore.GREEN}Created backup at {backup_path}{Style.RESET_ALL}")
            except Exception as e:
                print(f"{Fore.RED}Error creating backup: {e}{Style.RESET_ALL}")
                return False
            
            # Write updated map
            try:
                with open(tunnel_map_path, "w") as f:
                    json.dump(tunnel_map, f, indent=2)
                print(f"{Fore.GREEN}✅ Updated tunnel_id_map.json for all {len(mismatches)} mismatches{Style.RESET_ALL}")
            except Exception as e:
                print(f"{Fore.RED}Error updating tunnel_id_map.json: {e}{Style.RESET_ALL}")
                return False
        
        # If fix option is enabled, ask for confirmation
        elif fix:
            if input(f"{Fore.YELLOW}Do you want to update tunnel_id_map.json to match DNS? (y/n): {Style.RESET_ALL}").lower() == 'y':
                for mismatch in mismatches:
                    tunnel_map[mismatch['fqdn']] = mismatch['dns_tunnel_id']
                
                # Backup the original file
                backup_path = tunnel_map_path + ".backup"
                try:
                    with open(backup_path, "w") as f:
                        json.dump(tunnel_map, f, indent=2)
                    print(f"{Fore.GREEN}Created backup at {backup_path}{Style.RESET_ALL}")
                except Exception as e:
                    print(f"{Fore.RED}Error creating backup: {e}{Style.RESET_ALL}")
                    return False
                
                # Write updated map
                try:
                    with open(tunnel_map_path, "w") as f:
                        json.dump(tunnel_map, f, indent=2)
                    print(f"{Fore.GREEN}✅ Updated tunnel_id_map.json to match DNS records{Style.RESET_ALL}")
                except Exception as e:
                    print(f"{Fore.RED}Error updating tunnel_id_map.json: {e}{Style.RESET_ALL}")
                    return False
    
    # Return success if no mismatches
    return len(mismatches) == 0

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Validate Cloudflare tunnel mappings against DNS records")
    parser.add_argument("--fix", action="store_true", help="Interactively fix mismatches by updating tunnel_id_map.json")
    parser.add_argument("--auto-fix", action="store_true", help="Automatically fix mismatches without confirmation")
    parser.add_argument("--dry-run", action="store_true", help="Simulate auto-fix without making changes")
    parser.add_argument("--verbose", "-v", action="store_true", help="Show detailed progress")
    args = parser.parse_args()
    
    success = validate_tunnels(fix=args.fix, auto_fix=args.auto_fix, verbose=args.verbose, dry_run=args.dry_run)
    
    if success and not args.verbose:
        print(f"\n{Fore.GREEN}All tunnel mappings are valid!{Style.RESET_ALL}")
    
    sys.exit(0 if success else 1)