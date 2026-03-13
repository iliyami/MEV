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
BACK_ATTACKER_ID = 2

def extract_committed_blocks(log_files: List[str]) -> Tuple[List[Tuple[int, int]], dict]:
    """Extract committed blocks (authority_index, height) from log files"""
    committed_blocks = []
    author_to_index = {}
    
    all_authors = set()
    for log_file in log_files:
        try:
            with open(log_file, 'r') as file:
                for line in file:
                    match = re.search(r'Committed B(\d+)\(([^)]+)\)', line)
                    if match:
                        author_str = match.group(2)
                        all_authors.add(author_str)
        except FileNotFoundError:
            continue
    
    sorted_authors = sorted(all_authors)
    for idx, author_str in enumerate(sorted_authors):
        author_to_index[author_str] = idx
    
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
    
    return committed_blocks, author_to_index

def calculate_mev_metrics(committed_blocks: List[Tuple[int, int]], attack_type: str):
    """Calculate Advanced MEV Metrics (ASR, BSR, SSR) with distance histogram"""
    
    # 1. Group blocks by height (round) to analyze intra-round ordering
    rounds = defaultdict(list)
    for pos, (auth, height) in enumerate(committed_blocks):
        rounds[height].append((auth, pos))  # Store auth AND global position
        
    total_victims = 0
    frontrun_success = 0
    backrun_success = 0
    sandwich_success = 0
    backrun_gaps = []  # Track distance for histogram
    
    # Analyze each round where a victim block exists
    for height, participants_with_pos in rounds.items():
        participants = [auth for auth, _ in participants_with_pos]
        positions = [pos for _, pos in participants_with_pos]
        
        if VICTIM_ID in participants:
            total_victims += 1
            vic_idx = participants.index(VICTIM_ID)
            vic_global_pos = positions[vic_idx]
            
            # Frontrun: Attacker 0 is before Victim
            if ATTACKER_ID in participants:
                att_idx = participants.index(ATTACKER_ID)
                att_global_pos = positions[att_idx]
                if att_idx < vic_idx:
                    frontrun_success += 1
            
            # Backrun: Attacker (0) is after Victim
            if ATTACKER_ID in participants:
                att_idx = participants.index(ATTACKER_ID)
                att_global_pos = positions[att_idx]
                if att_idx > vic_idx:
                    backrun_success += 1
                    gap = att_global_pos - vic_global_pos
                    backrun_gaps.append(gap)
                    
            # Sandwich: Attacker 0 before (gap <= 3) AND (Attacker 2 or 0) after (gap <= 3)
            if ATTACKER_ID in participants:
                front_idx = participants.index(ATTACKER_ID)
                front_global_pos = positions[front_idx]
                if front_idx < vic_idx and (vic_global_pos - front_global_pos) <= 3:
                    if participants.count(ATTACKER_ID) > 1:
                        back_idx = len(participants) - 1 - participants[::-1].index(ATTACKER_ID)
                        back_global_pos = positions[back_idx]
                        if back_idx > vic_idx and (back_global_pos - vic_global_pos) <= 3:
                            sandwich_success += 1

    asr = (frontrun_success / total_victims * 100) if total_victims > 0 else 0
    bsr = (backrun_success / total_victims * 100) if total_victims > 0 else 0
    ssr = (sandwich_success / total_victims * 100) if total_victims > 0 else 0
    
    print(f"\n📊 MEV Metrics (Attack Type: {attack_type}):")
    print(f"   Total Victim Blocks: {total_victims}")
    print(f"   Frontrun Success (ASR): {asr:.2f}% ({frontrun_success}/{total_victims})")
    print(f"   Backrun Success (BSR):  {bsr:.2f}% ({backrun_success}/{total_victims})")
    print(f"   Sandwich Success (SSR): {ssr:.2f}% ({sandwich_success}/{total_victims})")

    # Emit FINAL_BACKRUN_STATS for backrun attacks
    if attack_type == "backrun" and total_victims > 0:
        l1_count = sum(1 for g in backrun_gaps if g == 1)
        l2_count = sum(1 for g in backrun_gaps if g in (2, 3))
        l1_asr = (l1_count / total_victims * 100) if total_victims > 0 else 0
        l2_asr = (l2_count / total_victims * 100) if total_victims > 0 else 0
        import json
        stats = {"l1_asr": round(l1_asr, 2), "l2_asr": round(l2_asr, 2), "histogram": backrun_gaps}
        print(f"FINAL_BACKRUN_STATS: {json.dumps(stats)}")

    # Emit FINAL_SANDWICH_STATS for sandwich attacks
    if attack_type == "sandwich" and total_victims > 0:
        import json
        stats = {"sesr": round(ssr, 2)}
        print(f"FINAL_SANDWICH_STATS: {json.dumps(stats)}")
    
    return asr, bsr, ssr

def analyze_block_distribution(committed_blocks: List[Tuple[int, int]]):
    """Show distribution of blocks per authority"""
    from collections import Counter
    
    authorities = [auth for auth, _ in committed_blocks]
    distribution = Counter(authorities)
    
    print(f"\n📈 Block Distribution by Authority:")
    for auth in sorted(distribution.keys()):
        count = distribution[auth]
        marker = ""
        if auth == ATTACKER_ID: marker = " 🎯 FRONT-ATTACKER"
        elif auth == VICTIM_ID: marker = " 🎯 VICTIM"
        elif auth == BACK_ATTACKER_ID: marker = " 🎯 BACK-ATTACKER"
        print(f"   Node {auth:2d}: {count:4d} blocks{marker}")

def check_attack_logs(log_files: List[str]) -> str:
    """Check if attack was actually executed and return type"""
    import os
    env_attack_type = os.environ.get("ATTACK_TYPE")
    if env_attack_type in ["frontrun", "backrun", "sandwich"]:
        print(f"\n✅ Attack type '{env_attack_type}' detected from environment.")
        return env_attack_type

    patterns = {
        "frontrun": r"FISSURE \(frontrun\):",
        "backrun": r"FISSURE \(backrun\):",
        "sandwich": r"FISSURE \(sandwich\):"
    }
    
    detected_type = "unknown"
    for filename in log_files:
        try:
            with open(filename, 'r') as file:
                content = file.read()
                for atype, pat in patterns.items():
                    if re.search(pat, content):
                        detected_type = atype
                        break
        except: continue
        if detected_type != "unknown": break
            
    if detected_type != "unknown":
        print(f"\n✅ Attack ({detected_type}) detected in logs")
    else:
        print(f"\n⚠️  Warning: No attack logs found!")
    return detected_type

def main():
    if len(sys.argv) < 2:
        print("Usage: python3 calculate-fissure-asr.py <logfile1> ...")
        sys.exit(1)
    
    log_files = sys.argv[1:]
    print("\n" + "="*60)
    print("🎯 AUTOBAHN MEV SUCCESS ANALYSIS")
    print("="*60)
    
    attack_type = check_attack_logs(log_files)
    committed_blocks, _ = extract_committed_blocks(log_files)
    
    if not committed_blocks:
        print("\n❌ No blocks found.")
        sys.exit(1)
        
    analyze_block_distribution(committed_blocks)
    asr, bsr, ssr = calculate_mev_metrics(committed_blocks, attack_type)
    
    print("\n" + "="*60)
    if attack_type == "backrun":
        score = bsr
        metric = "BSR"
    elif attack_type == "sandwich":
        score = ssr
        metric = "SSR"
    else:
        score = asr
        metric = "ASR"
        
    print(f"🎯 FINAL SUCCESS RATE ({metric}): {score:.2f}%")
    print("="*60)

if __name__ == "__main__":
    main()

