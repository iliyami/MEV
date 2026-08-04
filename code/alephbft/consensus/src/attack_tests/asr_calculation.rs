//! ASR calculation helpers for AlephBFT attack tests.

use crate::{OrderedUnit, Round};
use aleph_bft_mock::{Data, Hasher64};
use std::collections::BTreeMap;

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
enum AttackType {
    Frontrun,
    Backrun,
    Sandwich,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
enum NodeRole {
    FrontAttacker,
    Victim,
    BackAttacker,
    Honest,
}

#[derive(Clone, Debug)]
struct AttackLayout {
    front_attackers: std::ops::Range<usize>,
    victims: std::ops::Range<usize>,
    back_attackers: std::ops::Range<usize>,
}

#[derive(Clone, Copy, Debug)]
struct UnitRecord {
    creator: usize,
    height: usize,
    round: Round,
}

impl AttackType {
    fn from_env() -> Self {
        match std::env::var("ATTACK_TYPE")
            .unwrap_or_else(|_| "frontrun".to_string())
            .as_str()
        {
            "backrun" => Self::Backrun,
            "sandwich" => Self::Sandwich,
            _ => Self::Frontrun,
        }
    }
}

impl AttackLayout {
    fn new(num_nodes: usize, num_attackers: usize, num_victims: usize, attack_type: AttackType) -> Self {
        match attack_type {
            AttackType::Frontrun => Self {
                front_attackers: 0..num_attackers,
                victims: num_nodes.saturating_sub(num_victims)..num_nodes,
                back_attackers: 0..0,
            },
            AttackType::Backrun => Self {
                front_attackers: 0..0,
                victims: 0..num_victims,
                back_attackers: num_victims..num_victims + num_attackers,
            },
            AttackType::Sandwich => {
                let front = num_attackers / 2;
                let back = num_attackers - front;
                let victims_start = front;
                let back_start = victims_start + num_victims;
                Self {
                    front_attackers: 0..front,
                    victims: victims_start..victims_start + num_victims,
                    back_attackers: back_start..back_start + back,
                }
            }
        }
    }

    fn role(&self, node: usize) -> NodeRole {
        if self.front_attackers.contains(&node) {
            NodeRole::FrontAttacker
        } else if self.victims.contains(&node) {
            NodeRole::Victim
        } else if self.back_attackers.contains(&node) {
            NodeRole::BackAttacker
        } else {
            NodeRole::Honest
        }
    }
}

fn attack_mode() -> String {
    std::env::var("ATTACK_MODE").unwrap_or_default()
}

fn extract_units(finalized_units: &[OrderedUnit<Data, Hasher64>]) -> Vec<UnitRecord> {
    finalized_units
        .iter()
        .enumerate()
        .map(|(height, unit)| UnitRecord {
            creator: unit.creator.0,
            height,
            round: unit.round,
        })
        .collect()
}

/// Measurement-only instrumentation (no protocol effect). Emits the neutral
/// all-pairs ASR: over every attacker x victim pair, the fraction where the
/// attacker unit finalizes before the victim unit (att position < vic position).
/// Fair, unbiased ordering scores ~50%. Also dumps the raw attacker/victim
/// finalization positions so an external harness can recompute it independently.
fn print_neutral_all_pairs(
    finalized_units: &[OrderedUnit<Data, Hasher64>],
    num_nodes: usize,
    num_attackers: usize,
    num_victims: usize,
) {
    let layout = AttackLayout::new(num_nodes, num_attackers, num_victims, AttackType::Frontrun);
    let all_units = extract_units(finalized_units);
    // (round, finalization-position) per role.
    let mut att: Vec<(u64, usize)> = Vec::new();
    let mut vic: Vec<(u64, usize)> = Vec::new();
    for u in &all_units {
        match layout.role(u.creator) {
            NodeRole::FrontAttacker => att.push((u.round as u64, u.height)),
            NodeRole::Victim => vic.push((u.round as u64, u.height)),
            _ => {}
        }
    }
    if att.len() < 2 || vic.is_empty() {
        println!("FINAL_ALL_PAIRS_ASR: n/a (att={}, vic={})", att.len(), vic.len());
        return;
    }
    // Neutral all-pairs: over every attacker x victim pair, fraction att pos < vic pos.
    let mut ap_succ: u64 = 0;
    let mut ap_tot: u64 = 0;
    // Same-round ASR (classical frontrun): among pairs in the SAME commit round,
    // fraction where the attacker finalizes before the victim. Clean 50% null.
    let mut sr_succ: u64 = 0;
    let mut sr_tot: u64 = 0;
    for &(ar, ah) in &att {
        for &(vr, vh) in &vic {
            ap_tot += 1;
            if ah < vh {
                ap_succ += 1;
            }
            if ar == vr {
                sr_tot += 1;
                if ah < vh {
                    sr_succ += 1;
                }
            }
        }
    }
    println!(
        "FINAL_ALL_PAIRS_ASR: {:.2}%",
        ap_succ as f64 / ap_tot as f64 * 100.0
    );
    if sr_tot > 0 {
        println!(
            "FINAL_SAME_ROUND_ASR: {:.2}% (n_pairs={})",
            sr_succ as f64 / sr_tot as f64 * 100.0,
            sr_tot
        );
    } else {
        println!("FINAL_SAME_ROUND_ASR: n/a (no same-round att/vic pairs)");
    }
}

fn histogram_json(histogram: &BTreeMap<String, usize>) -> String {
    let parts = histogram
        .iter()
        .map(|(gap, count)| format!("\"{}\":{}", gap, count))
        .collect::<Vec<_>>();
    format!("{{{}}}", parts.join(","))
}

fn allowed_round_gap_for_backrun(mode: &str) -> i64 {
    if mode == "sluggish" {
        6
    } else {
        0
    }
}

fn sandwich_metric_mode() -> String {
    std::env::var("SANDWICH_METRIC_MODE").unwrap_or_else(|_| "strict".to_string())
}

/// Paper-aligned frontrun calculation.
pub fn calculate_asr_paper_aligned(
    finalized_units: &[OrderedUnit<Data, Hasher64>],
    num_nodes: usize,
    num_attackers: usize,
    num_victims: usize,
) -> f64 {
    if AttackType::from_env() != AttackType::Frontrun {
        return calculate_asr_paper_aligned_advanced(
            finalized_units,
            num_nodes,
            num_attackers,
            num_victims,
        );
    }

    if finalized_units.is_empty() {
        log::warn!("No finalized units to calculate ASR");
        return 0.0;
    }

    let layout = AttackLayout::new(num_nodes, num_attackers, num_victims, AttackType::Frontrun);
    let all_units = extract_units(finalized_units);

    // Measurement-only: emit the neutral 50%-null all-pairs ASR + raw positions.
    print_neutral_all_pairs(finalized_units, num_nodes, num_attackers, num_victims);

    let mut victim_blocks = Vec::new();
    let mut attacker_blocks = Vec::new();
    for unit in &all_units {
        match layout.role(unit.creator) {
            NodeRole::FrontAttacker => attacker_blocks.push((unit.height, unit.round)),
            NodeRole::Victim => victim_blocks.push((unit.height, unit.round)),
            _ => {}
        }
    }

    log::info!(
        "   Attacker blocks: {}, Victim blocks: {}",
        attacker_blocks.len(),
        victim_blocks.len()
    );

    if attacker_blocks.is_empty() || victim_blocks.is_empty() {
        log::warn!("Missing attacker or victim blocks");
        return 0.0;
    }

    let mut successes = 0;
    let mut total_trials = 0;
    for (vic_height, vic_round) in &victim_blocks {
        let mut candidate_attackers: Vec<(usize, Round)> = attacker_blocks
            .iter()
            .filter(|(_, att_round)| *att_round >= *vic_round)
            .copied()
            .collect();

        if candidate_attackers.is_empty() {
            continue;
        }

        candidate_attackers.sort_by_key(|(_, att_round)| *att_round as i64 - *vic_round as i64);
        let (att_height, _) = candidate_attackers[0];
        total_trials += 1;
        if att_height < *vic_height {
            successes += 1;
        }
    }

    if total_trials == 0 {
        log::warn!("No valid trials found (no attacker blocks created after victim blocks)");
        return 0.0;
    }

    let asr = (successes as f64 / total_trials as f64) * 100.0;
    println!("FINAL_ASR_RESULT: {:.2}%", asr);
    log::info!(
        "   ASR calculation (closest-match): {}/{} trials = {:.2}%",
        successes,
        total_trials,
        asr
    );
    asr / 100.0
}

/// Advanced metrics for backrun and sandwich attack types.
pub fn calculate_asr_paper_aligned_advanced(
    finalized_units: &[OrderedUnit<Data, Hasher64>],
    num_nodes: usize,
    num_attackers: usize,
    num_victims: usize,
) -> f64 {
    if finalized_units.is_empty() {
        log::warn!("No finalized units to calculate ASR");
        return 0.0;
    }

    let attack_type = AttackType::from_env();
    if attack_type == AttackType::Frontrun {
        return calculate_asr_paper_aligned(finalized_units, num_nodes, num_attackers, num_victims);
    }

    let layout = AttackLayout::new(num_nodes, num_attackers, num_victims, attack_type);
    let mode = attack_mode();
    let round_gap = allowed_round_gap_for_backrun(&mode);
    let all_units = extract_units(finalized_units);

    let victims = all_units
        .iter()
        .copied()
        .filter(|unit| layout.role(unit.creator) == NodeRole::Victim)
        .collect::<Vec<_>>();
    let front_attackers = all_units
        .iter()
        .copied()
        .filter(|unit| layout.role(unit.creator) == NodeRole::FrontAttacker)
        .collect::<Vec<_>>();
    let back_attackers = all_units
        .iter()
        .copied()
        .filter(|unit| layout.role(unit.creator) == NodeRole::BackAttacker)
        .collect::<Vec<_>>();

    if victims.is_empty() {
        log::warn!("Missing victim blocks");
        return 0.0;
    }

    if attack_type == AttackType::Backrun {
        if back_attackers.is_empty() {
            log::warn!("Missing back attacker blocks");
            return 0.0;
        }

        let mut histogram: BTreeMap<String, usize> = BTreeMap::new();
        let mut successful_victims = 0usize;
        let mut l1_successes = 0usize;
        let mut l2_successes = 0usize;

        for victim in &victims {
            let best_gap = back_attackers
                .iter()
                .filter(|att| att.height > victim.height)
                .filter(|att| {
                    let diff = att.round as i64 - victim.round as i64;
                    diff >= 0 && diff <= round_gap
                })
                .map(|att| att.height - victim.height)
                .min();

            if let Some(gap) = best_gap {
                successful_victims += 1;
                if gap == 1 {
                    l1_successes += 1;
                }
                if gap <= 2 {
                    l2_successes += 1;
                }
                let bucket = if gap >= 10 {
                    "10+".to_string()
                } else {
                    gap.to_string()
                };
                *histogram.entry(bucket).or_insert(0) += 1;
            }
        }

        let total_victims = victims.len();
        let cumulative_asr = (successful_victims as f64 / total_victims as f64) * 100.0;
        let l1_asr = (l1_successes as f64 / total_victims as f64) * 100.0;
        let l2_asr = (l2_successes as f64 / total_victims as f64) * 100.0;

        println!(
            "FINAL_BACKRUN_STATS: {{\"l1_asr\": {:.2}, \"l2_asr\": {:.2}, \"cumulative_asr\": {:.2}, \"histogram\": {}}}",
            l1_asr,
            l2_asr,
            cumulative_asr,
            histogram_json(&histogram)
        );
        println!("FINAL_ASR_RESULT: {:.2}%", cumulative_asr);
        return cumulative_asr / 100.0;
    }

    if front_attackers.is_empty() || back_attackers.is_empty() {
        log::warn!("Missing front or back attacker blocks");
        return 0.0;
    }

    let metric_mode = sandwich_metric_mode();
    let sesr = if metric_mode == "triplet" {
        let mut successes = 0usize;
        let mut total_triplets = 0usize;
        for front in &front_attackers {
            for victim in &victims {
                let front_round_diff = victim.round as i64 - front.round as i64;
                if front_round_diff < 0 || front_round_diff > round_gap {
                    continue;
                }
                for back in &back_attackers {
                    let back_round_diff = back.round as i64 - victim.round as i64;
                    if back_round_diff < 0 || back_round_diff > round_gap {
                        continue;
                    }
                    total_triplets += 1;
                    if front.height < victim.height && victim.height < back.height {
                        successes += 1;
                    }
                }
            }
        }

        if total_triplets == 0 {
            log::warn!("No comparable sandwich triplets found");
            0.0
        } else {
            let sesr = (successes as f64 / total_triplets as f64) * 100.0;
            println!(
                "FINAL_SANDWICH_STATS: {{\"sesr\": {:.2}, \"successful_triplets\": {}, \"total_triplets\": {}, \"metric_mode\": \"{}\"}}",
                sesr,
                successes,
                total_triplets,
                metric_mode
            );
            sesr
        }
    } else {
        let mut sandwiched_victims = 0usize;
        let height_to_role = all_units
            .iter()
            .map(|unit| (unit.height, layout.role(unit.creator)))
            .collect::<BTreeMap<_, _>>();
        for victim in &victims {
            let front_is_adjacent = victim
                .height
                .checked_sub(1)
                .and_then(|height| height_to_role.get(&height))
                .is_some_and(|role| *role == NodeRole::FrontAttacker);
            let back_is_adjacent = height_to_role
                .get(&(victim.height + 1))
                .is_some_and(|role| *role == NodeRole::BackAttacker);

            if front_is_adjacent && back_is_adjacent {
                sandwiched_victims += 1;
            }
        }

        let sesr = (sandwiched_victims as f64 / victims.len() as f64) * 100.0;
        println!(
            "FINAL_SANDWICH_STATS: {{\"sesr\": {:.2}, \"sandwiched_victims\": {}, \"total_victims\": {}, \"metric_mode\": \"{}\"}}",
            sesr,
            sandwiched_victims,
            victims.len(),
            metric_mode
        );
        sesr
    };
    println!("FINAL_ASR_RESULT: {:.2}%", sesr);
    sesr / 100.0
}
