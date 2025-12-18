#!/usr/bin/env python3
"""
Calculate Attack Success Rate (ASR) for Fissure attack on Autobahn
Based on paper: https://eprint.iacr.org/2024/1496.pdf
"""

import re
import sys
from typing import List, Tuple
from collections import defaultdict

ATTACKER_ID = 0
VICTIM_ID = 1

def extract_committed_blocks(log_files: List[str]) -> Tuple[List[Tuple[int, int]], dict]:
    """Extract committed blocks (authority_index, height) from log files"""
    # Pattern: "Committed B{height}({author_public_key})"
    # We need to map public keys to authority indices
    # Public keys in logs are displayed as hex strings
    committed_blocks = []
    author_to_index = {}
    index_to_author = {}
    
    # First pass: collect all unique authors and map them to indices
    # Sort by author string to ensure consistent ordering (matching BTreeMap order)
    all_authors = set()
    for log_file in log_files:
        try:
            with open(log_file, 'r') as file:
                for line in file:
                    # Look for "Committed B{height}({author})" pattern
                    match = re.search(r'Committed B(\d+)\(([^)]+)\)', line)
                    if match:
                        author_str = match.group(2)
                        all_authors.add(author_str)
        except FileNotFoundError:
            print(f"⚠️  Warning: File {log_file} not found")
            continue
    
    # Sort authors to get consistent ordering (matching BTreeMap sorted order)
    sorted_authors = sorted(all_authors)
    for idx, author_str in enumerate(sorted_authors):
        author_to_index[author_str] = idx
        index_to_author[idx] = author_str
    
    # Second pass: extract committed blocks with indices
    for log_file in log_files:
        try:
            with open(log_file, 'r') as file:
                for line in file:
                    match = re.search(r'Committed B(\d+)\(([^)]+)\)', line)
                    if match:
                        height = int(match.group(1))
                        author_str = match.group(2)
                        if author_str in author_to_index:
                            authority = author_to_index[author_str]
                            committed_blocks.append((authority, height))
        except FileNotFoundError:
            continue
    
    return committed_blocks, index_to_author

def build_global_order(log_files: List[str]) -> Tuple[List[Tuple[int, int]], dict]:
    """Build global ordering from committed blocks across all nodes"""
    committed_blocks, index_to_author = extract_committed_blocks(log_files)
    
    if not committed_blocks:
        print("❌ Error: No committed blocks found in any log file!")
        return [], {}
    
    # Remove duplicates while preserving order (first occurrence wins)
    seen = set()
    unique_blocks = []
    for block in committed_blocks:
        if block not in seen:
            seen.add(block)
            unique_blocks.append(block)
    
    print(f"📦 Total committed blocks found: {len(unique_blocks)}")
    
    return unique_blocks, index_to_author

def calculate_asr(committed_blocks: List[Tuple[int, int]], index_to_author: dict) -> float:
    """Calculate Attack Success Rate (ASR)"""
    
    # Find all attacker and victim blocks
    attacker_positions = []
    victim_positions = []
    
    for pos, (authority, height) in enumerate(committed_blocks):
        if authority == ATTACKER_ID:
            attacker_positions.append((pos, height))
        elif authority == VICTIM_ID:
            victim_positions.append((pos, height))
    
    print(f"\n📊 Block Statistics:")
    print(f"   Total blocks in order: {len(committed_blocks)}")
    print(f"   Attacker blocks (Node {ATTACKER_ID}): {len(attacker_positions)}")
    print(f"   Victim blocks (Node {VICTIM_ID}): {len(victim_positions)}")
    
    if not attacker_positions or not victim_positions:
        print(f"\n⚠️  Warning: Missing attacker or victim blocks!")
        return 0.0
    
    # Count successful frontrunning (attacker before victim)
    successes = 0
    total_pairs = 0
    
    for att_pos, att_height in attacker_positions:
        for vic_pos, vic_height in victim_positions:
            total_pairs += 1
            if att_pos < vic_pos:
                successes += 1
    
    asr = (successes / total_pairs) * 100.0 if total_pairs > 0 else 0.0
    
    print(f"\n🎯 ASR Calculation:")
    print(f"   Total pairs analyzed: {total_pairs:,}")
    print(f"   Successful frontrunning: {successes:,}")
    print(f"   Failed frontrunning: {total_pairs - successes:,}")
    
    return asr

def analyze_block_distribution(committed_blocks: List[Tuple[int, int]]):
    """Show distribution of blocks per authority"""
    from collections import Counter
    
    authorities = [auth for auth, _ in committed_blocks]
    distribution = Counter(authorities)
    
    print(f"\n📈 Block Distribution by Authority:")
    for auth in sorted(distribution.keys()):
        count = distribution[auth]
        percentage = (count / len(committed_blocks)) * 100
        marker = ""
        if auth == ATTACKER_ID:
            marker = " 🎯 ATTACKER"
        elif auth == VICTIM_ID:
            marker = " 🎯 VICTIM"
        print(f"   Node {auth:2d}: {count:4d} blocks ({percentage:5.2f}%){marker}")

def check_attack_logs(log_files: List[str]):
    """Check if attack was actually executed"""
    fissure_pattern = r"FISSURE: Attacker.*excluding victim"
    leader_support_pattern = r"LEADER_SUPPORT: Attacker.*excluding victim"
    attack_found = False
    attack_type = None
    exclusion_count = 0
    
    for filename in log_files:
        if "primary-0" in filename or "node-0" in filename:  # Check attacker's log
            try:
                with open(filename, 'r') as file:
                    for line in file:
                        if re.search(leader_support_pattern, line):
                            attack_found = True
                            attack_type = "Leader Support"
                            exclusion_count += 1
                        elif re.search(fissure_pattern, line):
                            attack_found = True
                            attack_type = "Fissure"
                            exclusion_count += 1
            except FileNotFoundError:
                continue
    
    if attack_found:
        print(f"\n✅ {attack_type} attack detected: {exclusion_count} victim proposals excluded")
    else:
        print(f"\n⚠️  Warning: No attack logs found!")
        print(f"   The attack may not have been activated.")

def main():
    if len(sys.argv) < 2:
        print("Usage: python3 calculate-fissure-asr.py <logfile1> <logfile2> ...")
        sys.exit(1)
    
    log_files = sys.argv[1:]
    
    print("\n" + "="*60)
    print("🎯 FISSURE ATTACK ASR ANALYSIS (Autobahn)")
    print("="*60)
    
    # Check if attack was executed
    check_attack_logs(log_files)
    
    # Build global order
    committed_blocks, index_to_author = build_global_order(log_files)
    
    if not committed_blocks:
        print("\n❌ Failed to extract committed blocks from logs")
        sys.exit(1)
    
    # Show block distribution
    analyze_block_distribution(committed_blocks)
    
    # Calculate ASR
    asr = calculate_asr(committed_blocks, index_to_author)
    
    # Print final result
    print("\n" + "="*60)
    print(f"🎯 FINAL ATTACK SUCCESS RATE (ASR): {asr:.2f}%")
    print("="*60)
    
    # Interpretation
    print(f"\n📝 Interpretation:")
    if asr > 55:
        print(f"   ✅ HIGH SUCCESS: Attack is highly effective!")
    elif asr > 50:
        print(f"   ✅ MODERATE SUCCESS: Attack provides advantage")
    elif asr > 45:
        print(f"   ⚠️  LOW SUCCESS: Minimal attack advantage")
    else:
        print(f"   ❌ FAILED: No significant attack advantage")
    
    print(f"\n   Baseline (no attack): ~50%")
    print(f"   Improvement: {asr - 50:.2f}%")
    print(f"\n   Paper reference: https://eprint.iacr.org/2024/1496.pdf")
    print()

if __name__ == "__main__":
    main()

