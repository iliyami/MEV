// Analysis: Mysticeti ASR Validity Check
//
// Key Concerns:
// 1. Leader election is round-robin: (round + offset) % 13
//    - In 13-node network: 4 attackers (indices 0-3), 3 victims (indices 10-12), 6 honest (4-9)
//    - Leader indices: round % 13
//    - Round 0: index 0 (attacker) ✓
//    - Round 3: index 3 (attacker) ✓
//    - Round 6: index 6 (honest)
//    - Round 9: index 9 (honest)
//    - Round 12: index 12 (victim)
//    - Attackers are leaders 4/13 = ~31% naturally
//    - Victims are leaders 3/13 = ~23% naturally
//
// 2. If victim leaders are elected but can't get votes (due to exclusion):
//    - They get SKIPPED (not committed)
//    - But victim blocks may still appear in commits from:
//      a) Indirect commits (via later committed leader)
//      b) Honest nodes including victim blocks
//
// 3. ASR measures: attacker blocks ordered before victim blocks
//    - If victims are excluded → fewer victim blocks in commits
//    - This naturally increases ASR (fewer victim blocks = higher chance attacker before)
//    - But is this "real" attack success or just exclusion side effect?
//
// 4. Need to verify:
//    - Baseline ASR (no attack) should be ~50% (random)
//    - With attack: Are we seeing >50% because:
//      a) Attackers actually getting priority? (real success)
//      b) Victim blocks excluded → fewer victim blocks? (measurement artifact)
//      c) Leader election bias? (protocol artifact)
