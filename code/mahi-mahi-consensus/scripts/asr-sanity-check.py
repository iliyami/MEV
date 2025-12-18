#!/usr/bin/env python3
"""
ASR Sanity Check Script
Validates if the ASR calculation makes sense given the throughput and participation
"""

import sys
import re
from collections import defaultdict

def analyze_attack_effectiveness(log_files):
    """Analyze the true effectiveness of the attack"""
    
    # Parse environment for attack config
    ATTACKER_ID = 0
    VICTIM_ID = 1
    
    print("=" * 60)
    print("ASR SANITY CHECK ANALYSIS")
    print("=" * 60)
    
    # Collect all committed blocks with their positions
    all_blocks = []
    blocks_by_node = defaultdict(list)
    commit_counts = defaultdict(int)
    log_lines_by_node = {}
    
    for log_file in log_files:
        # Extract node ID from filename
        match = re.search(r'v(\d+)\.log', log_file)
        if not match:
            continue
        node_id = int(match.group(1))
        
        # Count log lines as a proxy for activity
        with open(log_file, 'r') as f:
            lines = f.readlines()
            log_lines_by_node[node_id] = len(lines)
            
            for line in lines:
                # Look for commit messages
                if "Committing block" in line or "Commit " in line:
                    commit_counts[node_id] += 1
                    
                # Look for blocks in commit order
                commit_match = re.search(r'authority:(\d+) round:(\d+)', line)
                if commit_match and "Commit" in line:
                    authority = int(commit_match.group(1))
                    round_num = int(commit_match.group(2))
                    blocks_by_node[authority].append((len(all_blocks), round_num))
                    all_blocks.append((authority, round_num))
    
    print("\n📊 Node Activity Analysis:")
    print("-" * 40)
    
    # Check for isolation
    attacker_lines = log_lines_by_node.get(ATTACKER_ID, 0)
    victim_lines = log_lines_by_node.get(VICTIM_ID, 0)
    avg_lines = sum(log_lines_by_node.values()) / len(log_lines_by_node) if log_lines_by_node else 0
    
    print(f"Attacker (Node {ATTACKER_ID}) log lines: {attacker_lines:,}")
    print(f"Victim (Node {VICTIM_ID}) log lines: {victim_lines:,}")
    print(f"Average node log lines: {avg_lines:,.0f}")
    
    if attacker_lines < avg_lines * 0.5:
        print("⚠️  WARNING: Attacker has <50% average activity - likely isolated!")
    
    print("\n📊 Commit Activity:")
    print("-" * 40)
    for node_id in sorted(commit_counts.keys()):
        commits = commit_counts[node_id]
        marker = "🔮 ATTACKER" if node_id == ATTACKER_ID else "🎯 VICTIM" if node_id == VICTIM_ID else ""
        print(f"Node {node_id}: {commits:,} commits {marker}")
    
    attacker_commits = commit_counts.get(ATTACKER_ID, 0)
    avg_commits = sum(commit_counts.values()) / len(commit_counts) if commit_counts else 0
    
    if attacker_commits < avg_commits * 0.5:
        print(f"\n⚠️  WARNING: Attacker has only {attacker_commits/avg_commits:.1%} of average commits!")
        print("   This indicates severe connectivity issues or isolation.")
    
    # Calculate traditional ASR
    attacker_blocks = blocks_by_node.get(ATTACKER_ID, [])
    victim_blocks = blocks_by_node.get(VICTIM_ID, [])
    
    print("\n📊 Block Production:")
    print("-" * 40)
    print(f"Attacker blocks in final order: {len(attacker_blocks)}")
    print(f"Victim blocks in final order: {len(victim_blocks)}")
    
    if len(attacker_blocks) == 0:
        print("\n❌ ATTACK FAILED: Attacker produced no blocks!")
        return
    
    # Calculate ASR
    successes = 0
    total_pairs = 0
    
    for att_pos, att_round in attacker_blocks:
        for vic_pos, vic_round in victim_blocks:
            total_pairs += 1
            if att_pos < vic_pos:
                successes += 1
    
    asr = (successes / total_pairs * 100) if total_pairs > 0 else 0
    
    print("\n📊 Traditional ASR Calculation:")
    print("-" * 40)
    print(f"Total pairs: {total_pairs:,}")
    print(f"Successes: {successes:,}")
    print(f"ASR: {asr:.2f}%")
    
    # Calculate effective ASR (considering throughput)
    expected_blocks = len(all_blocks) / 13  # 13 nodes
    attacker_ratio = len(attacker_blocks) / expected_blocks if expected_blocks > 0 else 0
    effective_asr = asr * attacker_ratio
    
    print("\n📊 Effective ASR (considering throughput):")
    print("-" * 40)
    print(f"Expected attacker blocks: {expected_blocks:.0f}")
    print(f"Actual attacker blocks: {len(attacker_blocks)}")
    print(f"Attacker participation: {attacker_ratio:.1%}")
    print(f"Effective ASR: {effective_asr:.2f}%")
    
    print("\n🔍 Sanity Check Results:")
    print("=" * 60)
    
    if attacker_ratio < 0.5:
        print("❌ UNREALISTIC: Attacker is isolated or near-isolated")
        print(f"   - Producing only {attacker_ratio:.1%} of expected blocks")
        print(f"   - Traditional ASR of {asr:.1f}% is misleading")
        print(f"   - Effective ASR is only {effective_asr:.1f}%")
    elif attacker_ratio < 0.8:
        print("⚠️  DEGRADED: Attacker has reduced throughput")
        print(f"   - Producing {attacker_ratio:.1%} of expected blocks")
        print(f"   - Traditional ASR: {asr:.1f}%")
        print(f"   - Effective ASR: {effective_asr:.1f}%")
    else:
        print("✅ REALISTIC: Attacker maintains good throughput")
        print(f"   - Producing {attacker_ratio:.1%} of expected blocks")
        print(f"   - Traditional ASR: {asr:.1f}%")
        print(f"   - This appears to be a sustainable attack")
    
    print("\n💡 Interpretation:")
    if asr > 80 and attacker_ratio < 0.2:
        print("The high ASR is an artifact of severe throughput reduction.")
        print("The attacker is cherry-picking very few blocks, not sustainably attacking.")
    elif asr > 60 and attacker_ratio > 0.7:
        print("This appears to be a successful and sustainable attack!")
    elif asr < 55:
        print("The attack provides minimal advantage over baseline.")
    
if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(f"Usage: {sys.argv[0]} <log_files>")
        sys.exit(1)
    
    analyze_attack_effectiveness(sys.argv[1:])





