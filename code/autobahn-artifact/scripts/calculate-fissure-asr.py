#!/usr/bin/env python3
"""
Autobahn MEV metric calculation for frontrun, backrun, and sandwich attacks.
"""

import os
import re
import sys
import json
from collections import Counter, defaultdict
from typing import Dict, Iterable, List, Optional, Tuple


def env_int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, default))
    except ValueError:
        return default


ATTACK_TYPE = os.environ.get("ATTACK_TYPE", "frontrun")
SANDWICH_METRIC_MODE = os.environ.get("SANDWICH_METRIC_MODE", "strict")
FRONT_ATTACKER_ID = env_int("FRONT_ATTACKER_ID", env_int("ATTACKER_ID", 0))
VICTIM_ID = env_int("VICTIM_ID", 1)
BACK_ATTACKER_ID = env_int("BACK_ATTACKER_ID", env_int("ATTACKER_ID", 2))


def extract_committed_blocks(log_files: Iterable[str]) -> Tuple[List[Tuple[int, int]], Dict[int, str]]:
    committed_blocks: List[Tuple[int, int]] = []
    author_to_index: Dict[str, int] = {}
    index_to_author: Dict[int, str] = {}

    authors = set()
    for log_file in log_files:
        try:
            with open(log_file, "r") as handle:
                for line in handle:
                    match = re.search(r"Committed B(\d+)\(([^)]+)\)", line)
                    if match:
                        authors.add(match.group(2))
        except FileNotFoundError:
            continue

    for idx, author in enumerate(sorted(authors)):
        author_to_index[author] = idx
        index_to_author[idx] = author

    for log_file in log_files:
        try:
            with open(log_file, "r") as handle:
                for line in handle:
                    match = re.search(r"Committed B(\d+)\(([^)]+)\)", line)
                    if match and match.group(2) in author_to_index:
                        committed_blocks.append((author_to_index[match.group(2)], int(match.group(1))))
        except FileNotFoundError:
            continue

    seen = set()
    unique_blocks = []
    for block in committed_blocks:
        if block not in seen:
            seen.add(block)
            unique_blocks.append(block)

    return unique_blocks, index_to_author


def group_by_height(committed_blocks: Iterable[Tuple[int, int]]) -> Dict[int, List[int]]:
    rounds: Dict[int, List[int]] = defaultdict(list)
    for authority, height in committed_blocks:
        rounds[height].append(authority)
    return rounds


def analyze_block_distribution(committed_blocks: List[Tuple[int, int]]) -> None:
    distribution = Counter(authority for authority, _ in committed_blocks)
    print("\n📈 Block Distribution by Authority:")
    for authority in sorted(distribution):
        marker = ""
        if authority == FRONT_ATTACKER_ID:
            marker = " 🎯 FRONT"
        elif authority == VICTIM_ID:
            marker = " 🎯 VICTIM"
        elif authority == BACK_ATTACKER_ID:
            marker = " 🎯 BACK"
        print(f"   Node {authority:2d}: {distribution[authority]:4d} blocks{marker}")


def calculate_frontrun_asr(committed_blocks: List[Tuple[int, int]]) -> float:
    attacker_positions = [idx for idx, (authority, _) in enumerate(committed_blocks) if authority == FRONT_ATTACKER_ID]
    victim_positions = [idx for idx, (authority, _) in enumerate(committed_blocks) if authority == VICTIM_ID]
    if not attacker_positions or not victim_positions:
        print("\n⚠️  Missing attacker or victim blocks")
        return 0.0

    successes = 0
    total_pairs = 0
    for attacker_pos in attacker_positions:
        for victim_pos in victim_positions:
            total_pairs += 1
            if attacker_pos < victim_pos:
                successes += 1

    asr = (successes / total_pairs) * 100.0 if total_pairs else 0.0
    print("\n🎯 Frontrun ASR:")
    print(f"   Total pairs analyzed: {total_pairs}")
    print(f"   Successful pairs: {successes}")
    print(f"FINAL_ASR_RESULT: {asr:.2f}%")
    return asr


def calculate_backrun_metrics(rounds: Dict[int, List[int]]) -> float:
    total_victims = 0
    successful_victims = 0
    l1_successes = 0
    l2_successes = 0
    histogram: Dict[str, int] = defaultdict(int)

    for participants in rounds.values():
        if VICTIM_ID not in participants:
            continue
        total_victims += 1
        victim_index = participants.index(VICTIM_ID)
        gaps = [idx - victim_index for idx, authority in enumerate(participants) if authority == BACK_ATTACKER_ID and idx > victim_index]
        if not gaps:
            continue
        best_gap = min(gaps)
        successful_victims += 1
        if best_gap == 1:
            l1_successes += 1
        if best_gap <= 2:
            l2_successes += 1
        histogram[str(best_gap if best_gap < 10 else "10+")] += 1

    cumulative_asr = (successful_victims / total_victims) * 100.0 if total_victims else 0.0
    l1_asr = (l1_successes / total_victims) * 100.0 if total_victims else 0.0
    l2_asr = (l2_successes / total_victims) * 100.0 if total_victims else 0.0

    print("\n🎯 Backrun Metrics:")
    print(f"   Victim rounds: {total_victims}")
    print(f"   Successful backruns: {successful_victims}")
    ordered_histogram = dict(
        sorted(
            histogram.items(),
            key=lambda item: (item[0] == "10+", int(item[0]) if item[0] != "10+" else 10),
        )
    )
    print(
        "FINAL_BACKRUN_STATS: "
        + json.dumps(
            {
                "l1_asr": round(l1_asr, 2),
                "l2_asr": round(l2_asr, 2),
                "cumulative_asr": round(cumulative_asr, 2),
                "histogram": ordered_histogram,
            },
            sort_keys=True,
        )
    )
    print(f"FINAL_ASR_RESULT: {cumulative_asr:.2f}%")
    return cumulative_asr


def calculate_sandwich_metrics(committed_blocks: List[Tuple[int, int]]) -> float:
    if SANDWICH_METRIC_MODE == "triplet":
        rounds = group_by_height(committed_blocks)
        successful_triplets = 0
        total_triplets = 0

        for participants in rounds.values():
            front_positions = [idx for idx, authority in enumerate(participants) if authority == FRONT_ATTACKER_ID]
            victim_positions = [idx for idx, authority in enumerate(participants) if authority == VICTIM_ID]
            back_positions = [idx for idx, authority in enumerate(participants) if authority == BACK_ATTACKER_ID]

            for front_index in front_positions:
                for victim_index in victim_positions:
                    for back_index in back_positions:
                        total_triplets += 1
                        if front_index < victim_index < back_index:
                            successful_triplets += 1

        sesr = (successful_triplets / total_triplets) * 100.0 if total_triplets else 0.0
        print("\n🎯 Sandwich Metrics:")
        print(f"   Metric mode: {SANDWICH_METRIC_MODE}")
        print(f"   Comparable triplets: {total_triplets}")
        print(f"   Successful triplets: {successful_triplets}")
        print(
            "FINAL_SANDWICH_STATS: "
            + json.dumps(
                {
                    "sesr": round(sesr, 2),
                    "successful_triplets": successful_triplets,
                    "total_triplets": total_triplets,
                    "metric_mode": SANDWICH_METRIC_MODE,
                },
                sort_keys=True,
            )
        )
        print(f"FINAL_ASR_RESULT: {sesr:.2f}%")
        return sesr

    victim_positions = [idx for idx, (authority, _) in enumerate(committed_blocks) if authority == VICTIM_ID]
    total_victims = len(victim_positions)
    sandwiched_victims = 0

    for victim_index in victim_positions:
        if victim_index == 0 or victim_index == len(committed_blocks) - 1:
            continue
        front_authority = committed_blocks[victim_index - 1][0]
        back_authority = committed_blocks[victim_index + 1][0]
        if front_authority == FRONT_ATTACKER_ID and back_authority == BACK_ATTACKER_ID:
            sandwiched_victims += 1

    sesr = (sandwiched_victims / total_victims) * 100.0 if total_victims else 0.0
    print("\n🎯 Sandwich Metrics:")
    print(f"   Metric mode: {SANDWICH_METRIC_MODE}")
    print(f"   Victim blocks: {total_victims}")
    print(f"   Sandwiched victims: {sandwiched_victims}")
    print(
        "FINAL_SANDWICH_STATS: "
        + json.dumps(
            {
                "sesr": round(sesr, 2),
                "sandwiched_victims": sandwiched_victims,
                "total_victims": total_victims,
                "metric_mode": SANDWICH_METRIC_MODE,
            },
            sort_keys=True,
        )
    )
    print(f"FINAL_ASR_RESULT: {sesr:.2f}%")
    return sesr


def main() -> None:
    if len(sys.argv) < 2:
        print("Usage: python3 calculate-fissure-asr.py <logfile1> <logfile2> ...")
        sys.exit(1)

    log_files = sys.argv[1:]
    committed_blocks, index_to_author = extract_committed_blocks(log_files)

    print("\n" + "=" * 60)
    print("🎯 AUTOBAHN MEV ANALYSIS")
    print("=" * 60)
    print(f"Attack Type: {ATTACK_TYPE}")
    print(f"Sandwich Metric Mode: {SANDWICH_METRIC_MODE}")
    print(f"Front Attacker: {FRONT_ATTACKER_ID}")
    print(f"Victim: {VICTIM_ID}")
    print(f"Back Attacker: {BACK_ATTACKER_ID}")

    if not committed_blocks:
        print("\n❌ No committed blocks found in any log file.")
        sys.exit(1)

    print(f"\n📦 Total committed blocks found: {len(committed_blocks)}")
    if index_to_author:
        analyze_block_distribution(committed_blocks)

    rounds = group_by_height(committed_blocks)

    if ATTACK_TYPE == "backrun":
        score = calculate_backrun_metrics(rounds)
        metric = "BSR"
    elif ATTACK_TYPE == "sandwich":
        score = calculate_sandwich_metrics(committed_blocks)
        metric = "SeSR"
    else:
        score = calculate_frontrun_asr(committed_blocks)
        metric = "ASR"

    print("\n" + "=" * 60)
    print(f"🎯 FINAL SUCCESS RATE ({metric}): {score:.2f}%")
    print("=" * 60)


if __name__ == "__main__":
    main()
