#!/usr/bin/env python3
"""
Calculate Attack Success Rate (ASR) for Sluggish attack on Mahi-Mahi
"""

import re
import sys
from typing import List, Tuple

import os

# Configuration from environment or defaults
ATTACKER_ID = int(os.environ.get("ATTACKER_ID", 0))
VICTIM_ID = int(os.environ.get("VICTIM_ID", 1))

# Map authority letters to numbers (A=0, B=1, ...)
AUTH_MAP = {chr(65 + i): i for i in range(26)}

def extract_committed_blocks(filename: str) -> List[Tuple[int, int]]:
    """Extract committed blocks (authority, round) from log file"""
    # Pattern: "Decided Commit(A5)" where A-Z represents authority 0-25, and number is round
    pattern = r"Decided Commit\(([A-Z])(\d+)\)"
    committed_blocks = []
    
    try:
        with open(filename, 'r') as file:
            for line in file:
                match = re.search(pattern, line)
                if match:
                    authority_letter = match.group(1)
                    round_num = int(match.group(2))
                    if authority_letter in AUTH_MAP:
                        authority = AUTH_MAP[authority_letter]
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
            marker = " 🐌 ATTACKER (Sluggish)"
        elif auth == VICTIM_ID:
            marker = " 🎯 VICTIM"
        print(f"   Node {auth:2d}: {count:4d} blocks ({percentage:5.2f}%){marker}")

def check_attack_logs(log_files: List[str]):
    """Check if attack was actually executed"""
    sluggish_pattern = r"SLUGGISH: Node \d+ delaying"
    hybrid_pattern = r"HYBRID_SLUGGISH:"
    
    attack_mode = None
    delay_count = 0
    exclusion_count = 0
    
    for filename in log_files:
        if "v0.log" in filename:  # Only check attacker's log
            try:
                with open(filename, 'r') as file:
                    for line in file:
                        if re.search(sluggish_pattern, line):
                            attack_mode = "sluggish" if attack_mode != "hybrid" else attack_mode
                            delay_count += 1
                        if re.search(hybrid_pattern, line):
                            attack_mode = "hybrid"
                            if "Excluded" in line and "victim blocks" in line:
                                # Extract exclusion count from log
                                match = re.search(r"Excluded (\d+) victim blocks", line)
                                if match:
                                    exclusion_count = int(match.group(1))
            except FileNotFoundError:
                continue
    
    if attack_mode == "hybrid":
        print(f"\n✅ Hybrid Sluggish attack detected:")
        print(f"   - Timing delays applied: {delay_count} times")
        print(f"   - Victim blocks excluded: {exclusion_count}")
    elif attack_mode == "sluggish":
        print(f"\n✅ Pure Sluggish attack detected:")
        print(f"   - Timing delays applied: {delay_count} times")
    else:
        print(f"\n⚠️  Warning: No Sluggish attack logs found!")
        print(f"   The attack may not have been activated.")

def analyze_round_distribution(committed_blocks: List[Tuple[int, int]]):
    """Analyze round distribution to see if sluggish attack created round gaps"""
    attacker_rounds = [r for auth, r in committed_blocks if auth == ATTACKER_ID]
    victim_rounds = [r for auth, r in committed_blocks if auth == VICTIM_ID]
    
    if attacker_rounds and victim_rounds:
        avg_att_round = sum(attacker_rounds) / len(attacker_rounds)
        avg_vic_round = sum(victim_rounds) / len(victim_rounds)
        
        print(f"\n🔄 Round Analysis:")
        print(f"   Attacker average round: {avg_att_round:.2f}")
        print(f"   Victim average round: {avg_vic_round:.2f}")
        print(f"   Round gap: {avg_vic_round - avg_att_round:.2f}")
        
        if avg_att_round < avg_vic_round:
            print(f"   ✅ Attacker staying in lower rounds (as intended)")
        elif avg_att_round > avg_vic_round:
            print(f"   ⚠️  Attacker in higher rounds (unexpected)")
        else:
            print(f"   ⚠️  No significant round gap")

def main():
    if len(sys.argv) < 2:
        print("Usage: python3 calculate-sluggish-asr.py <logfile1> <logfile2> ...")
        sys.exit(1)
    
    log_files = sys.argv[1:]
    
    print("\n" + "="*60)
    print("🐌 SLUGGISH ATTACK ASR ANALYSIS")
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
    
    # Analyze round distribution
    analyze_round_distribution(committed_blocks)
    
    # Calculate ASR
    asr = calculate_asr(committed_blocks)
    
    # Print final result
    print("\n" + "="*60)
    print(f"🐌 FINAL ATTACK SUCCESS RATE (ASR): {asr:.2f}%")
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
    
    print(f"\n   Comparison:")
    print(f"   - Mysticeti Sluggish ASR: 40%")
    print(f"   - Mahi-Mahi Sluggish ASR: {asr:.2f}%")
    print()

if __name__ == "__main__":
    main()





