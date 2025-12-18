#!/usr/bin/env python3
"""
Calculate Attack Success Rate (ASR) for Speculative attack on Mahi-Mahi
Based on paper: https://eprint.iacr.org/2024/1496.pdf Section 4.2
"""

import re
import sys
from typing import List, Tuple

ATTACKER_ID = 0
VICTIM_ID = 1

def extract_committed_blocks(filename: str) -> List[Tuple[int, int]]:
    """Extract committed blocks (authority, round) from log file"""
    # Pattern: "Decided Commit(A5)" where A-M represents authority 0-12, and number is round
    pattern = r"Decided Commit\(([A-M])(\d+)\)"
    committed_blocks = []
    
    # Map authority letters to numbers (A=0, B=1, ..., M=12)
    auth_map = {chr(65 + i): i for i in range(13)}  # A-M -> 0-12

    try:
        with open(filename, 'r') as file:
            for line in file:
                match = re.search(pattern, line)
                if match:
                    authority_letter = match.group(1)
                    round_num = int(match.group(2))
                    authority = auth_map[authority_letter]
                    committed_blocks.append((authority, round_num))
    except FileNotFoundError:
        print(f"⚠️  Warning: File {filename} not found")
        return []

    return committed_blocks

def build_global_order(log_files: List[str]) -> List[Tuple[int, int]]:
    """Build global ordering from committed blocks across all nodes"""
    # Use the node with most commits as reference (usually all nodes should agree)
    all_commits = [extract_committed_blocks(f) for f in log_files]
    
    # Filter out empty lists
    all_commits = [c for c in all_commits if c]
    
    if not all_commits:
        print("❌ Error: No committed blocks found in any log file!")
        return []
    
    # Find longest sequence (most complete)
    longest = max(all_commits, key=len)
    
    print(f"📦 Total committed blocks found: {len(longest)}")
    
    # Verify consistency across nodes
    for i, commits in enumerate(all_commits):
        if len(commits) < len(longest):
            print(f"⚠️  Node {i}: {len(commits)} blocks (missing {len(longest) - len(commits)})")
    
    return longest

def calculate_asr(committed_blocks: List[Tuple[int, int]]) -> float:
    """Calculate Attack Success Rate (ASR)"""
    
    # Find all attacker and victim blocks
    attacker_positions = []
    victim_positions = []
    
    for pos, (authority, round_num) in enumerate(committed_blocks):
        if authority == ATTACKER_ID:
            attacker_positions.append((pos, round_num))
        elif authority == VICTIM_ID:
            victim_positions.append((pos, round_num))
    
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
    
    for att_pos, att_round in attacker_positions:
        for vic_pos, vic_round in victim_positions:
            total_pairs += 1
            if att_pos < vic_pos:
                successes += 1
    
    asr = (successes / total_pairs) * 100.0 if total_pairs > 0 else 0.0
    
    print(f"\n🎯 ASR Calculation:")
    print(f"   Total pairs analyzed: {total_pairs}")
    print(f"   Successful frontrunning: {successes}")
    print(f"   Failed frontrunning: {total_pairs - successes}")
    
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
            marker = " 🔮 ATTACKER"
        elif auth == VICTIM_ID:
            marker = " 🎯 VICTIM"
        print(f"   Node {auth:2d}: {count:4d} blocks ({percentage:5.2f}%){marker}")

def check_attack_logs(log_files: List[str]):
    """Check if attack was actually executed"""
    simple_pattern = r"SPECULATIVE \(Simple\): Attacker \d+ excluding victim \d+ block"
    sophisticated_pattern = r"SPECULATIVE \(Sophisticated\): Generating \d+ candidates"
    hybrid_pattern = r"SPECULATIVE \(Hybrid\):"
    traversal_pattern = r"SPECULATIVE \(Traversal\):"
    simple_found = False
    sophisticated_found = False
    hybrid_found = False
    traversal_found = False
    simple_exclusion_count = 0
    candidate_generation_count = 0
    hybrid_exclusion_count = 0
    
    for filename in log_files:
        if "v0.log" in filename:  # Only check attacker's log
            try:
                with open(filename, 'r') as file:
                    for line in file:
                        if re.search(simple_pattern, line):
                            simple_found = True
                            simple_exclusion_count += 1
                        if re.search(sophisticated_pattern, line):
                            sophisticated_found = True
                            candidate_generation_count += 1
                        if re.search(hybrid_pattern, line):
                            hybrid_found = True
                            if "Excluding victim block" in line:
                                hybrid_exclusion_count += 1
                        if re.search(traversal_pattern, line):
                            traversal_found = True
            except FileNotFoundError:
                continue
    
    if hybrid_found:
        print(f"\n✅ Speculative attack (Hybrid) detected: {hybrid_exclusion_count} victim blocks excluded + traversal optimization")
    elif simple_found:
        print(f"\n✅ Speculative attack (Simple) detected: {simple_exclusion_count} victim blocks excluded")
    elif sophisticated_found:
        print(f"\n✅ Speculative attack (Sophisticated) detected: {candidate_generation_count} candidate generations")
    elif traversal_found:
        print(f"\n✅ Speculative attack (Traversal) detected: DAG traversal optimization applied")
    else:
        print(f"\n⚠️  Warning: No Speculative attack logs found!")
        print(f"   The attack may not have been activated.")

def main():
    if len(sys.argv) < 2:
        print("Usage: python3 calculate-speculative-asr.py <logfile1> <logfile2> ...")
        sys.exit(1)
    
    log_files = sys.argv[1:]
    
    print("\n" + "="*60)
    print("🔮 SPECULATIVE ATTACK ASR ANALYSIS")
    print("="*60)
    
    # Check if attack was executed
    check_attack_logs(log_files)
    
    # Build global order
    committed_blocks = build_global_order(log_files)
    
    if not committed_blocks:
        print("\n❌ Failed to extract committed blocks from logs")
        sys.exit(1)
    
    # Show block distribution
    analyze_block_distribution(committed_blocks)
    
    # Calculate ASR
    asr = calculate_asr(committed_blocks)
    
    # Print final result
    print("\n" + "="*60)
    print(f"🔮 FINAL ATTACK SUCCESS RATE (ASR): {asr:.2f}%")
    print("="*60)
    
    # Interpretation
    print(f"\n📝 Interpretation:")
    if asr > 70:
        print(f"   ✅ EXCELLENT: Attack is highly effective! (Target: 60-75%)")
    elif asr >= 60:
        print(f"   ✅ SUCCESS: Attack meets target ASR range (60-75%)")
    elif asr > 55:
        print(f"   ✅ GOOD: Attack provides significant advantage")
    elif asr > 50:
        print(f"   ⚠️  MODERATE: Attack provides minimal advantage")
    else:
        print(f"   ❌ FAILED: No significant attack advantage")
    
    print(f"\n   Baseline (no attack): ~50%")
    print(f"   Improvement: {asr - 50:.2f}%")
    print(f"\n   Paper reference: https://eprint.iacr.org/2024/1496.pdf Section 4.2")
    print()

if __name__ == "__main__":
    main()

