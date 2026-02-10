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




