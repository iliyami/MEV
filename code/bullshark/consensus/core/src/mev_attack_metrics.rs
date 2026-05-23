use crate::{block::BlockAPI, commit::CommittedSubDag};
use std::collections::BTreeMap;
use tracing::{info, warn};

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
struct BlockRecord {
    creator: usize,
    position: usize,
    round: u32,
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

fn allowed_round_gap(mode: &str) -> i64 {
    if mode == "sluggish" {
        6
    } else {
        0
    }
}

fn sandwich_gap_k() -> usize {
    std::env::var("SANDWICH_GAP_K")
        .ok()
        .and_then(|s| s.parse().ok())
        .unwrap_or(0)
}

fn sandwich_metric_mode() -> String {
    std::env::var("SANDWICH_METRIC_MODE")
        .unwrap_or_else(|_| "strict".to_string())
}

fn histogram_json(histogram: &BTreeMap<String, usize>) -> String {
    let parts = histogram
        .iter()
        .map(|(gap, count)| format!("\"{}\":{}", gap, count))
        .collect::<Vec<_>>();
    format!("{{{}}}", parts.join(","))
}

fn extract_order(commits: &[CommittedSubDag]) -> Vec<BlockRecord> {
    let mut position = 0usize;
    let mut records = Vec::new();
    for commit in commits {
        for block in commit.blocks.iter() {
            records.push(BlockRecord {
                creator: block.author().value() as usize,
                position,
                round: block.round(),
            });
            position += 1;
        }
    }
    records
}

pub fn calculate_attack_score(
    commits: &[CommittedSubDag],
    num_validators: usize,
    num_attackers: usize,
    num_victims: usize,
) -> f64 {
    if commits.is_empty() {
        warn!("No commits to analyze");
        return 0.0;
    }

    let attack_type = AttackType::from_env();
    let mode = attack_mode();
    let round_gap = allowed_round_gap(&mode);
    let layout = AttackLayout::new(num_validators, num_attackers, num_victims, attack_type);
    let records = extract_order(commits);

    info!("Global order contains {} blocks", records.len());

    // v3 R-P2.1: emit committed-order records as JSON so the v2 harness
    // can compute per-policy ASR in Python (using the run's policy
    // vector from coordinator metrics). Built as a JSON string by hand
    // to avoid pulling serde_derive into consensus-core just for this
    // marker. The Python-side parser is
    // scripts/v2/benchmark.py::parse_committed_order.
    let order_json: String = records
        .iter()
        .map(|r| {
            format!(
                "{{\"creator\":{},\"position\":{},\"round\":{}}}",
                r.creator, r.position, r.round
            )
        })
        .collect::<Vec<_>>()
        .join(",");
    println!("FINAL_COMMITTED_ORDER: [{}]", order_json);

    let front_attackers = records
        .iter()
        .copied()
        .filter(|record| layout.role(record.creator) == NodeRole::FrontAttacker)
        .collect::<Vec<_>>();
    let victims = records
        .iter()
        .copied()
        .filter(|record| layout.role(record.creator) == NodeRole::Victim)
        .collect::<Vec<_>>();
    let back_attackers = records
        .iter()
        .copied()
        .filter(|record| layout.role(record.creator) == NodeRole::BackAttacker)
        .collect::<Vec<_>>();

    if victims.is_empty() {
        warn!("Missing victim blocks");
        return 0.0;
    }

    match attack_type {
        AttackType::Frontrun => {
            if front_attackers.is_empty() {
                warn!("Missing attacker blocks");
                return 0.0;
            }

            let mut successes = 0usize;
            let mut total_pairs = 0usize;
            for attacker in &front_attackers {
                for victim in &victims {
                    let comparable = if mode == "sluggish" {
                        let diff = victim.round as i64 - attacker.round as i64;
                        diff >= 0 && diff <= round_gap
                    } else {
                        attacker.round == victim.round
                    };
                    if comparable {
                        total_pairs += 1;
                        if attacker.position < victim.position {
                            successes += 1;
                        }
                    }
                }
            }

            if total_pairs == 0 {
                warn!("No comparable block pairs found");
                return 0.0;
            }

            let asr = (successes as f64 / total_pairs as f64) * 100.0;
            println!("FINAL_ASR_RESULT: {:.2}%", asr);
            asr
        }
        AttackType::Backrun => {
            if back_attackers.is_empty() {
                warn!("Missing back attacker blocks");
                return 0.0;
            }

            let mut histogram: BTreeMap<String, usize> = BTreeMap::new();
            let mut successful_victims = 0usize;
            let mut l1_successes = 0usize;
            let mut l2_successes = 0usize;

            for victim in &victims {
                let best_gap = back_attackers
                    .iter()
                    .filter(|attacker| attacker.position > victim.position)
                    .filter(|attacker| {
                        let diff = attacker.round as i64 - victim.round as i64;
                        diff >= 0 && diff <= round_gap
                    })
                    .map(|attacker| attacker.position - victim.position)
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
            cumulative_asr
        }
        AttackType::Sandwich => {
            if front_attackers.is_empty() || back_attackers.is_empty() {
                warn!("Missing front or back attacker blocks");
                return 0.0;
            }

            let metric_mode = sandwich_metric_mode();
            let gap_k = sandwich_gap_k();
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
                            if front.position < victim.position && victim.position < back.position {
                                successes += 1;
                            }
                        }
                    }
                }

                if total_triplets == 0 {
                    warn!("No comparable sandwich triplets found");
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
                let window = gap_k + 1;
                let position_to_record = records
                    .iter()
                    .map(|record| (record.position, *record))
                    .collect::<BTreeMap<_, _>>();
                for victim in &victims {
                    let front_found = (1..=window).any(|distance| {
                        victim
                            .position
                            .checked_sub(distance)
                            .and_then(|pos| position_to_record.get(&pos))
                            .is_some_and(|record| {
                                let round_diff = victim.round as i64 - record.round as i64;
                                layout.role(record.creator) == NodeRole::FrontAttacker
                                    && round_diff >= 0
                                    && round_diff <= round_gap
                            })
                    });
                    let back_found = (1..=window).any(|distance| {
                        position_to_record
                            .get(&(victim.position + distance))
                            .is_some_and(|record| {
                                let round_diff = record.round as i64 - victim.round as i64;
                                layout.role(record.creator) == NodeRole::BackAttacker
                                    && round_diff >= 0
                                    && round_diff <= round_gap
                            })
                    });
                    if front_found && back_found {
                        sandwiched_victims += 1;
                    }
                }

                let sesr = (sandwiched_victims as f64 / victims.len() as f64) * 100.0;
                println!(
                    "FINAL_SANDWICH_STATS: {{\"sesr\": {:.2}, \"sandwiched_victims\": {}, \"total_victims\": {}, \"gap_k\": {}, \"metric_mode\": \"{}\"}}",
                    sesr,
                    sandwiched_victims,
                    victims.len(),
                    gap_k,
                    metric_mode
                );
                sesr
            };
            println!("FINAL_ASR_RESULT: {:.2}%", sesr);
            sesr
        }
    }
}

pub fn calculate_pair_baseline_asr(
    commits: &[CommittedSubDag],
    attacker_id: usize,
    victim_id: usize,
) -> f64 {
    if commits.is_empty() {
        warn!("No commits to analyze");
        return 0.0;
    }
    if attacker_id == victim_id {
        warn!("Attacker and victim ids are identical");
        return 0.0;
    }

    let records = extract_order(commits);
    let attacker_positions = records
        .iter()
        .filter(|record| record.creator == attacker_id)
        .map(|record| record.position)
        .collect::<Vec<_>>();
    let victim_positions = records
        .iter()
        .filter(|record| record.creator == victim_id)
        .map(|record| record.position)
        .collect::<Vec<_>>();

    if attacker_positions.is_empty() || victim_positions.is_empty() {
        warn!("Missing attacker or victim blocks");
        return 0.0;
    }

    let mut successes = 0usize;
    let mut total_pairs = 0usize;
    for attacker in &attacker_positions {
        for victim in &victim_positions {
            total_pairs += 1;
            if attacker < victim {
                successes += 1;
            }
        }
    }

    if total_pairs == 0 {
        warn!("No comparable block pairs found");
        return 0.0;
    }

    let asr = (successes as f64 / total_pairs as f64) * 100.0;
    info!(
        "Pairwise baseline ASR for node {} vs node {}: {}/{} = {:.2}%",
        attacker_id,
        victim_id,
        successes,
        total_pairs,
        asr
    );
    asr
}
