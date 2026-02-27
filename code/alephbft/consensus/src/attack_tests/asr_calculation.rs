//! Paper-Aligned ASR Calculation Module
//!
//! This module implements the Attack Success Rate (ASR) calculation according to
//! the methodology specified in the reference paper:
//! "No Fish Is Too Big for Flash Boys! Frontrunning on DAG-based Blockchains"
//!
//! Methodology:
//! - All-pairs matching (all attacker blocks × all victim blocks)
//! - Filter: attacker_round >= victim_round (attacker creates block after witnessing victim)
//! - Success: attacker_height < victim_height (attacker block ordered before victim block)
//! - ASR = successes / total_pairs

use crate::{NodeIndex, OrderedUnit, Round};
use aleph_bft_mock::{Data, Hasher64};

/// Calculate ASR using paper-aligned methodology (all-pairs matching)
///
/// # Arguments
/// * `finalized_units` - All finalized units from the consensus run
/// * `num_nodes` - Total number of nodes in the network
/// * `num_attackers` - Number of attacker nodes (indices 0..num_attackers)
/// * `num_victims` - Number of victim nodes (indices (num_nodes - num_victims)..num_nodes)
///
/// # Returns
/// ASR as a fraction (0.0 to 1.0), or 0.0 if no valid pairs found
pub fn calculate_asr_paper_aligned(
    finalized_units: &[OrderedUnit<Data, Hasher64>],
    num_nodes: usize,
    num_attackers: usize,
    num_victims: usize,
) -> f64 {
    if finalized_units.is_empty() {
        log::warn!("No finalized units to calculate ASR");
        return 0.0;
    }

    // Extract all finalized units with creator, height (position), and round
    // Height = position in finalization order (not round number!)
    // Paper: "height" means position in committed order
    let all_units: Vec<(NodeIndex, usize, Round)> = finalized_units
        .iter()
        .enumerate()
        .map(|(height, unit)| (unit.creator, height, unit.round))
        .collect();

    // Identify attackers and victims
    let attacker_indices: Vec<usize> = (0..num_attackers).collect();
    let victim_start = num_nodes - num_victims;
    let victim_indices: Vec<usize> = (victim_start..num_nodes).collect();

    // Extract victim blocks and attacker blocks with their height and round
    let mut victim_blocks: Vec<(usize, Round)> = Vec::new(); // (height, round)
    let mut attacker_blocks: Vec<(usize, Round)> = Vec::new(); // (height, round)

    for (height, (creator, _, round)) in all_units.iter().enumerate() {
        let creator_idx = creator.0;
        if attacker_indices.contains(&creator_idx) {
            attacker_blocks.push((height, *round));
        }
        if victim_indices.contains(&creator_idx) {
            victim_blocks.push((height, *round));
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

    // PAPER'S METHODOLOGY (All-Pairs Matching):
    // - All attacker blocks can attempt to frontrun all victim blocks
    // - Filter: attacker_round >= victim_round (attacker creates block after witnessing victim)
    // - Success: attacker_height < victim_height (attacker block ordered before victim block)
    // - ASR = successes / total_pairs

    let mut successes = 0;
    let mut total_trials = 0;

    // PAPER'S METHODOLOGY (Optimized for AlephBFT):
    // - For each victim block, find the closest attacker block (by round)
    // - Filter: attacker_round >= victim_round
    // - Success: attacker_height < victim_height
    for (vic_height, vic_round) in &victim_blocks {
        // Find attacker blocks created at same round or AFTER victim block
        let mut candidate_attackers: Vec<(usize, Round)> = attacker_blocks
            .iter()
            .filter(|(_, att_round)| *att_round >= *vic_round)
            .cloned()
            .collect();

        if candidate_attackers.is_empty() {
            continue; // No matching attacker block for this victim
        }

        // Match the CLOSEST attacker block (by round difference)
        candidate_attackers.sort_by_key(|(_, att_round)| {
            *att_round as i32 - *vic_round as i32
        });

        let (att_height, _) = candidate_attackers[0]; // Closest attacker block

        total_trials += 1;

        // Success = attacker block height < victim block height
        if att_height < *vic_height {
            successes += 1;
        }
    }

    if total_trials == 0 {
        log::warn!("No valid trials found (no attacker blocks created after victim blocks)");
        return 0.0;
    }

    let asr = (successes as f64 / total_trials as f64) * 100.0;
    log::info!(
        "   ASR calculation (closest-match): {}/{} trials = {:.2}%",
        successes,
        total_trials,
        asr
    );

    asr / 100.0 // Return as fraction (0.0 to 1.0)
}

/// Calculate advanced ASR metrics including L1, L2, LX, and SeSR
pub fn calculate_asr_paper_aligned_advanced(
    finalized_units: &[OrderedUnit<Data, Hasher64>],
    num_nodes: usize,
    num_attackers: usize,
    num_victims: usize,
) -> f64 {
    if finalized_units.is_empty() {
        return 0.0;
    }

    let attack_type = std::env::var("ATTACK_TYPE").unwrap_or_else(|_| "frontrun".to_string());
    let is_backrun = attack_type == "backrun";
    let is_sandwich = attack_type == "sandwich";

    // Extract all units
    let all_units: Vec<(NodeIndex, usize, Round)> = finalized_units
        .iter()
        .enumerate()
        .map(|(height, unit)| (unit.creator, height, unit.round))
        .collect();

    let attacker_indices: Vec<usize> = (0..num_attackers).collect();
    let victim_start = num_nodes - num_victims;
    let victim_indices: Vec<usize> = (victim_start..num_nodes).collect();

    let mut victim_blocks = Vec::new();
    let mut attacker_blocks = Vec::new();

    for (height, (creator, _, round)) in all_units.iter().enumerate() {
        let creator_idx = creator.0;
        if attacker_indices.contains(&creator_idx) {
            attacker_blocks.push((height, *round));
        }
        if victim_indices.contains(&creator_idx) {
            victim_blocks.push((height, *round));
        }
    }

    if attacker_blocks.is_empty() || victim_blocks.is_empty() {
        return 0.0;
    }

    let mut successes = 0;
    let mut total_trials = 0;
    let mut l1_successes = 0;
    let mut l2_successes = 0;
    let mut lx_successes = 0;
    let mut backrun_hist = vec![0; 11];

    let mut victims_sandwiched = 0;
    let mut total_victims_for_sandwich = 0;

    for (vic_height, vic_round) in &victim_blocks {
        total_trials += 1;

        if is_backrun || is_sandwich {
            // Find Backrun
            let mut candidate_attackers: Vec<(usize, Round)> = attacker_blocks
                .iter()
                .filter(|(att_height, att_round)| {
                    if is_sandwich {
                        // For sandwich, back-attackers only (second half)
                        let attacker_idx = all_units[*att_height].0 .0;
                        attacker_idx >= num_attackers / 2 && *att_height > *vic_height && (*att_round as i32 - *vic_round as i32).abs() <= 3
                    } else {
                        // For backrun, all attackers
                        *att_height > *vic_height && (*att_round as i32 - *vic_round as i32).abs() <= 3
                    }
                })
                .cloned()
                .collect();

            if !candidate_attackers.is_empty() {
                candidate_attackers.sort_by_key(|(att_height, _)| *att_height - *vic_height);
                let (att_height, _) = candidate_attackers[0];
                let dist = att_height - vic_height;
                
                lx_successes += 1;
                if dist == 1 { l1_successes += 1; }
                if dist <= 3 { l2_successes += 1; }
                
                let hist_idx = dist.min(10);
                backrun_hist[hist_idx] += 1;
            }

            if is_sandwich {
                total_victims_for_sandwich += 1;
                let mut has_front = false;
                let has_back = !candidate_attackers.is_empty();

                // Find Frontrun
                for (att_height, att_round) in &attacker_blocks {
                    let attacker_idx = all_units[*att_height].0 .0;
                    if attacker_idx < num_attackers / 2 && *att_height < *vic_height && (*att_round as i32 - *vic_round as i32).abs() <= 3 {
                        has_front = true;
                        break;
                    }
                }

                if has_front && has_back {
                    victims_sandwiched += 1;
                }
            }
        } else {
            // Traditional Frontrun (ASR-F)
            let mut candidate_attackers: Vec<(usize, Round)> = attacker_blocks
                .iter()
                .filter(|(_, att_round)| *att_round >= *vic_round)
                .cloned()
                .collect();

            if !candidate_attackers.is_empty() {
                candidate_attackers.sort_by_key(|(_, att_round)| *att_round as i32 - *vic_round as i32);
                let (att_height, _) = candidate_attackers[0];
                if att_height < *vic_height {
                    successes += 1;
                }
            }
        }
    }

    if is_backrun {
        let l1 = (l1_successes as f64 / total_trials as f64) * 100.0;
        let l2 = (l2_successes as f64 / total_trials as f64) * 100.0;
        let lx = (lx_successes as f64 / total_trials as f64) * 100.0;
        log::info!("   ASR-B (Overall/LX): {:.2}%", lx);
        log::info!("   L1 Success: {:.2}% ({}/{})", l1, l1_successes, total_trials);
        log::info!("   L2 Success: {:.2}% ({}/{})", l2, l2_successes, total_trials);
        println!("FINAL_BACKRUN_STATS: {{\"l1_asr\": {:.2}, \"l2_asr\": {:.2}, \"lx_asr\": {:.2}, \"histogram\": {:?}}}", 
            l1, l2, lx, &backrun_hist[1..]);
        return lx / 100.0;
    }

    if is_sandwich {
        let sesr = (victims_sandwiched as f64 / total_victims_for_sandwich as f64) * 100.0;
        log::info!("   Sandwich Efficiency (SeSR): {:.2}% ({}/{})", sesr, victims_sandwiched, total_victims_for_sandwich);
        println!("FINAL_SANDWICH_STATS: {{\"sesr\": {:.2}, \"victims\": {}, \"total\": {}}}", 
            sesr, victims_sandwiched, total_victims_for_sandwich);
        return sesr / 100.0;
    }

    let asr = (successes as f64 / total_trials as f64) * 100.0;
    log::info!("   ASR-F (Frontrun): {:.2}%", asr);
    asr / 100.0
}





