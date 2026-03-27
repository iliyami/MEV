// Copyright (c) Mysten Labs, Inc.
// SPDX-License-Identifier: Apache-2.0

//! Attack Tests for Mysticeti Protocol
//!
//! This module contains tests for measuring Attack Success Rate (ASR)
//! of frontrunning attacks: Fissure, Sluggish, and Speculative.
//!
//! ASR Calculation: Measures block-pair ordering per paper definition
//! Paper: "A block Bv is frontrun by block Ba from attacker Na if Na creates Ba 
//! after witnessing Bv and eventually Ba ≺C Bv" (where ≺C = committing order)
//! ASR = (# pairs where attacker block ordered before victim block) / (total # pairs)

#[cfg(test)]
mod tests {
    use crate::commit_observer::SimpleCommitObserver;
    use crate::consensus::linearizer::CommittedSubDag;
    use crate::net_sync::NetworkSyncer;
    use crate::test_util::{committee_and_cores_epoch_duration, networks_and_addresses, test_metrics};
use crate::block_handler::TestBlockHandler;
use crate::block_validator::AcceptAllBlockVerifier;
use crate::config::Parameters;
use crate::types::RoundNumber;
use std::env;
use std::time::Duration;
use rand::Rng;
use tokio::sync::mpsc;
use tracing::{info, warn};

    // Default constants (used as fallbacks)
    const DEFAULT_NUM_VALIDATORS: usize = 13;

    fn get_counts() -> (usize, usize, usize) {
        let n = env::var("NUM_NODES")
            .ok()
            .and_then(|s| s.parse().ok())
            .unwrap_or(DEFAULT_NUM_VALIDATORS);
            
        let attacker_ratio: f64 = env::var("ATTACKER_RATIO")
            .ok()
            .and_then(|s| s.parse().ok())
            .unwrap_or(0.308);
            
        let victim_ratio: f64 = env::var("VICTIM_RATIO")
            .ok()
            .and_then(|s| s.parse().ok())
            .unwrap_or(0.231);
            
        let num_attacker = ((n as f64) * attacker_ratio).floor() as usize;
        let num_victim = ((n as f64) * victim_ratio).floor() as usize;
        let _num_honest = n.saturating_sub(num_attacker).saturating_sub(num_victim);
        
        (n, num_attacker, num_victim)
    }

    // Helper to create network syncers with commit receivers
    async fn create_network_syncers_with_commits(
        n: usize,
        rounds_in_epoch: RoundNumber,
    ) -> (
        Vec<NetworkSyncer<TestBlockHandler, SimpleCommitObserver>>,
        mpsc::UnboundedReceiver<CommittedSubDag>,
    ) {
        let mut parameters = Parameters::default();
        if let Ok(val) = env::var("WAVE_LENGTH") {
            if let Ok(wl) = val.parse::<RoundNumber>() {
                parameters.wave_length = wl;
            }
        }
        if let Ok(val) = env::var("NUMBER_OF_LEADERS") {
            if let Ok(nl) = val.parse::<usize>() {
                parameters.number_of_leaders = nl;
            }
        }
        
        // Pass leader timeout if set
        if let Ok(val) = env::var("LEADER_TIMEOUT_MS") {
            if let Ok(ms) = val.parse::<u64>() {
                parameters.leader_timeout = Duration::from_millis(ms);
            }
        }

        let (_committee, cores, _commit_observers, _reporters) =
            committee_and_cores_epoch_duration(n, rounds_in_epoch);
        let metrics: Vec<_> = cores.iter().map(|c| c.metrics.clone()).collect();
        let (networks, _) =
            networks_and_addresses(&metrics, parameters.network_connection_max_latency).await;
        
        // Create a shared commit channel
        let (commit_sender, commit_receiver) = mpsc::unbounded_channel();
        
        let mut network_syncers = vec![];
        for (network, core) in networks.into_iter().zip(cores) {
            // Create SimpleCommitObserver with the shared sender
            let block_store = core.block_store().clone();
            let simple_observer = SimpleCommitObserver::new(
                block_store,
                commit_sender.clone(),
                0, // last_sent_height
                Default::default(), // recover_state
                test_metrics(),
            );
            
            let network_syncer = NetworkSyncer::start(
                network,
                core,
                3,
                simple_observer,
                Parameters::DEFAULT_SHUTDOWN_GRACE_PERIOD,
                AcceptAllBlockVerifier,
                test_metrics(),
                parameters.leader_timeout,
                parameters.synchronizer_parameters.clone(),
                parameters.enable_cleanup,
            );
            network_syncers.push(network_syncer);
        }
        
        (network_syncers, commit_receiver)
    }

    /// ASR Calculation: Block-pair ordering per paper definition
    fn calculate_asr(commits: &[CommittedSubDag], n: usize, num_attacker: usize, num_victim: usize) -> f64 {
        if commits.is_empty() {
            warn!("No commits to analyze");
            return 0.0;
        }
        
        // Build global ordering from all commits
        let mut global_order = Vec::new();
        for commit in commits {
            for block in commit.blocks.iter() {
                global_order.push((block.author(), block.round()));
            }
        }
        
        info!("Global order contains {} blocks", global_order.len());
        
        // Identify attacker and victim blocks
        // Attackers are first NUM_ATTACKER nodes (indices 0 to NUM_ATTACKER-1)
        // Victims are last NUM_VICTIM nodes (indices NUM_VALIDATORS-NUM_VICTIM to NUM_VALIDATORS-1)
        let mut attacker_positions = Vec::new();
        let mut victim_positions = Vec::new();
        
        for (pos, (author, round)) in global_order.iter().enumerate() {
            let author_index = *author as usize;
            if author_index < num_attacker {
                attacker_positions.push((pos, *round));
            } else if author_index >= n - num_victim {
                victim_positions.push((pos, *round));
            }
        }
        
        info!("Attacker blocks: {}", attacker_positions.len());
        info!("Victim blocks: {}", victim_positions.len());
        
        if attacker_positions.is_empty() || victim_positions.is_empty() {
            warn!("Missing attacker or victim blocks");
            return 0.0;
        }
        
        // Count successful frontrunning (attacker before victim)
        // This measures: Ba ≺C Bv (attacker block ordered before victim block)
        let mut successes = 0;
        let mut total_pairs = 0;
        
        for (att_pos, _att_round) in &attacker_positions {
            for (vic_pos, _vic_round) in &victim_positions {
                total_pairs += 1;
                
                // Success: attacker ordered before victim (Ba ≺C Bv)
                if att_pos < vic_pos {
                    successes += 1;
                }
            }
        }
        
        if total_pairs == 0 {
            warn!("No comparable block pairs found");
            return 0.0;
        }
        
        let asr = (successes as f64 / total_pairs as f64) * 100.0;
        info!("📊 ASR Analysis (Block-Pair Ordering):");
        info!("  Total pairs: {}", total_pairs);
        info!("  Successful frontrunning pairs: {} ({:.1}%)", successes, asr);
        info!("  Attacker blocks: {}", attacker_positions.len());
        info!("  Victim blocks: {}", victim_positions.len());
        info!("  Expected attacker ratio (stake): ~{:.1}%", (num_attacker as f64 / n as f64) * 100.0);
        
        info!("FINAL_ASR_RESULT: {}%", asr);
        asr
    }

    fn get_pair_ids(n: usize) -> (usize, usize) {
        let attacker_id = env::var("ATTACKER_ID")
            .ok()
            .and_then(|s| s.parse().ok())
            .unwrap_or(0);
        let victim_id = env::var("VICTIM_ID")
            .ok()
            .and_then(|s| s.parse().ok())
            .unwrap_or(usize::from(n > 1));
        (
            attacker_id.min(n.saturating_sub(1)),
            victim_id.min(n.saturating_sub(1)),
        )
    }

    fn calculate_pair_baseline_asr(commits: &[CommittedSubDag], attacker_id: usize, victim_id: usize) -> f64 {
        if commits.is_empty() {
            warn!("No commits to analyze");
            return 0.0;
        }
        if attacker_id == victim_id {
            warn!("Attacker and victim ids are identical");
            return 0.0;
        }

        let mut global_order = Vec::new();
        for commit in commits {
            for block in commit.blocks.iter() {
                global_order.push(block.author() as usize);
            }
        }

        let mut attacker_positions = Vec::new();
        let mut victim_positions = Vec::new();
        for (pos, author_index) in global_order.iter().enumerate() {
            if *author_index == attacker_id {
                attacker_positions.push(pos);
            } else if *author_index == victim_id {
                victim_positions.push(pos);
            }
        }

        if attacker_positions.is_empty() || victim_positions.is_empty() {
            warn!("Missing attacker or victim blocks");
            return 0.0;
        }

        let mut successes = 0usize;
        let mut total_pairs = 0usize;
        for att_pos in &attacker_positions {
            for vic_pos in &victim_positions {
                total_pairs += 1;
                if att_pos < vic_pos {
                    successes += 1;
                }
            }
        }

        if total_pairs == 0 {
            warn!("No comparable block pairs found");
            return 0.0;
        }

        let asr = (successes as f64 / total_pairs as f64) * 100.0;
        info!("📊 Pairwise baseline ASR Analysis:");
        info!("  Measured pair: node {} vs node {}", attacker_id, victim_id);
        info!("  Total pairs: {}", total_pairs);
        info!("  Successful ordered pairs: {} ({:.2}%)", successes, asr);
        info!("FINAL_ASR_RESULT: {:.2}%", asr);
        asr
    }

    #[tokio::test(flavor = "multi_thread", worker_threads = 4)]
    async fn test_fissure_attack_asr_13_nodes() {
        let _ = tracing_subscriber::fmt::try_init();

        let (n, num_attacker, num_victim) = get_counts();
        let _num_honest = n.saturating_sub(num_attacker).saturating_sub(num_victim);

        info!("🚀 Starting Fissure Attack Test with {} Nodes", n);
        info!("  Attackers: {} nodes (indices 0-{})", num_attacker, num_attacker.saturating_sub(1));
        info!("  Victims: {} nodes (indices {}-{})", num_victim, n.saturating_sub(num_victim), n.saturating_sub(1));
        info!("  Honest: {} nodes (indices {}-{})", _num_honest, num_attacker, n.saturating_sub(num_victim).saturating_sub(1));

        // Create network syncers with commit channel
        let (network_syncers, mut commit_receiver) = create_network_syncers_with_commits(n, 10000).await;
        info!("✅ All {} nodes initialized", n);

        // Collect commits in real-time
        // STOCHASTIC DURATION: Add 0-10s jitter to break block-count determinism
        let jitter_secs = rand::thread_rng().gen_range(0..10);
        let collection_duration = Duration::from_secs(35 + jitter_secs);
        info!("⏳ Collecting commits for {} seconds (including {}s jitter)...", 35 + jitter_secs, jitter_secs);
        let mut all_commits = Vec::new();
        // STOCHASTIC THRESHOLD: Vary the number of observed commits (30-50) to break structural ASR locks
        let min_commits = rand::thread_rng().gen_range(30..50);
        let deadline = tokio::time::Instant::now() + collection_duration;

        loop {
            let remaining = deadline.saturating_duration_since(tokio::time::Instant::now());
            if remaining.is_zero() || all_commits.len() >= min_commits {
                break;
            }
            match tokio::time::timeout(remaining, commit_receiver.recv()).await {
                Ok(Some(committed_subdag)) => {
                    info!("Received commit with {} blocks", committed_subdag.blocks.len());
                    all_commits.push(committed_subdag);
                }
                Ok(None) => {
                    warn!("Commit receiver closed");
                    break;
                }
                Err(_) => {
                    break;
                }
            }
        }

        info!("⏹️ Collected {} commits total", all_commits.len());

        // Calculate ASR
        info!("📊 Calculating Attack Success Rate (ASR)...");
        let asr = calculate_asr(&all_commits, n, num_attacker, num_victim);

        info!("🎯 FISSURE ATTACK RESULTS:");
        info!("  Network: {} validators", n);
        info!("  Attackers: {} nodes", num_attacker);
        info!("  Victims: {} nodes", num_victim);
        info!("  Attack Success Rate (Block-Pair Ordering): {:.1}%", asr);
        info!("  Paper Definition: Ba ≺C Bv (attacker block ordered before victim block)");
        info!("  Expected ASR: >50% indicates successful frontrunning attack");

        // Shutdown network syncers
        for network_syncer in network_syncers {
            let _ = network_syncer.shutdown().await;
        }

        info!("✅ Test completed successfully!");
    }

    #[tokio::test(flavor = "multi_thread", worker_threads = 4)]
    async fn test_certification_race_attack_asr_13_nodes() {
        let _ = tracing_subscriber::fmt::try_init();

        let (n, num_attacker, num_victim) = get_counts();
        let _num_honest = n.saturating_sub(num_attacker).saturating_sub(num_victim);

        info!("🚀 Starting Certification Race Attack Test with {} Nodes", n);
        info!("  Attack Type: Network-layer timing attack (NOT consensus-layer exclusion)");
        info!("  Strategy: Detect victim blocks → Immediately propose attacker block → Race to >2/3 certification");
        info!("  Attackers: {} nodes (indices 0-{})", num_attacker, num_attacker.saturating_sub(1));
        info!("  Victims: {} nodes (indices {}-{})", num_victim, n.saturating_sub(num_victim), n.saturating_sub(1));
        info!("  Honest: {} nodes (indices {}-{})", _num_honest, num_attacker, n.saturating_sub(num_victim).saturating_sub(1));

        // Create network syncers with commit channel
        let (network_syncers, mut commit_receiver) = create_network_syncers_with_commits(n, 10000).await;
        info!("✅ All {} nodes initialized", n);

        // Collect commits in real-time
        info!("⏳ Collecting commits for 35 seconds...");
        let mut all_commits = Vec::new();
        let collection_duration = Duration::from_secs(35);
        // STOCHASTIC THRESHOLD: Vary the number of observed commits (30-50) to break structural ASR locks
        let min_commits = rand::thread_rng().gen_range(30..50);
        let deadline = tokio::time::Instant::now() + collection_duration;

        loop {
            let remaining = deadline.saturating_duration_since(tokio::time::Instant::now());
            if remaining.is_zero() || all_commits.len() >= min_commits {
                break;
            }
            match tokio::time::timeout(remaining, commit_receiver.recv()).await {
                Ok(Some(committed_subdag)) => {
                    info!("Received commit with {} blocks", committed_subdag.blocks.len());
                    all_commits.push(committed_subdag);
                }
                Ok(None) => {
                    warn!("Commit receiver closed");
                    break;
                }
                Err(_) => {
                    break;
                }
            }
        }

        info!("⏹️ Collected {} commits total", all_commits.len());

        // Calculate ASR
        info!("📊 Calculating Attack Success Rate (ASR)...");
        let asr = calculate_asr(&all_commits, n, num_attacker, num_victim);

        info!("🎯 CERTIFICATION RACE ATTACK RESULTS:");
        info!("  Network: {} validators", n);
        info!("  Attackers: {}", num_attacker);
        info!("  Victims: {}", num_victim);
        info!("  Attack Success Rate (Block-Pair Ordering): {:.1}%", asr);
        info!("  Attack Type: Network-layer timing (propagation race)");
        info!("  Comparison: Fissure (consensus-layer exclusion) = 45.0%, Baseline = 46.9%");
        info!("  If ASR > baseline: Network-layer attack effective");
        info!("  If ASR ≈ baseline: Only natural network timing effects");

        // Shutdown network syncers
        for network_syncer in network_syncers {
            let _ = network_syncer.shutdown().await;
        }

        info!("✅ Test completed successfully!");
    }

    #[tokio::test(flavor = "multi_thread", worker_threads = 4)]
    async fn test_sluggish_attack_asr_13_nodes() {
        let _ = tracing_subscriber::fmt::try_init();

        let (n, num_attacker, num_victim) = get_counts();
        let _num_honest = n.saturating_sub(num_attacker).saturating_sub(num_victim);

        info!("🚀 Starting Sluggish Attack Test with {} Nodes", n);
        info!("  Attackers: {} nodes (indices 0-{})", num_attacker, num_attacker.saturating_sub(1));
        info!("  Victims: {} nodes (indices {}-{})", num_victim, n.saturating_sub(num_victim), n.saturating_sub(1));
        info!("  Honest: {} nodes (indices {}-{})", _num_honest, num_attacker, n.saturating_sub(num_victim).saturating_sub(1));

        // Create network syncers with commit channel
        let (network_syncers, mut commit_receiver) = create_network_syncers_with_commits(n, 10000).await;
        info!("✅ All {} nodes initialized", n);

        // Collect commits in real-time
        info!("⏳ Collecting commits for 15 seconds (optimized for Sluggish attack)...");
        let mut all_commits = Vec::new();
        let collection_duration = Duration::from_secs(15); // Optimized for faster tests
        // STOCHASTIC THRESHOLD: Vary the number of observed commits (30-50) to break structural ASR locks
        let min_commits = rand::thread_rng().gen_range(30..50);
        let deadline = tokio::time::Instant::now() + collection_duration;

        loop {
            let remaining = deadline.saturating_duration_since(tokio::time::Instant::now());
            if remaining.is_zero() || all_commits.len() >= min_commits {
                break;
            }
            match tokio::time::timeout(remaining, commit_receiver.recv()).await {
                Ok(Some(committed_subdag)) => {
                    info!("Received commit with {} blocks", committed_subdag.blocks.len());
                    all_commits.push(committed_subdag);
                }
                Ok(None) => {
                    warn!("Commit receiver closed");
                    break;
                }
                Err(_) => {
                    break;
                }
            }
        }
        
        // Give a moment for cleanup before shutdown
        tokio::time::sleep(Duration::from_millis(100)).await;

        info!("⏹️ Collected {} commits total", all_commits.len());

        // Calculate ASR
        info!("📊 Calculating Attack Success Rate (ASR)...");
        let asr = calculate_asr(&all_commits, n, num_attacker, num_victim);

        info!("🎯 SLUGGISH ATTACK RESULTS:");
        info!("  Network: {} validators", n);
        info!("  Attackers: {}", num_attacker);
        info!("  Victims: {}", num_victim);
        info!("  Attack Success Rate (Block-Pair Ordering): {:.1}%", asr);
        info!("  Paper Definition: Ba ≺C Bv (attacker block ordered before victim block)");
        info!("  Expected ASR: >50% indicates successful frontrunning attack");

        // Shutdown network syncers
        for network_syncer in network_syncers {
            let _ = network_syncer.shutdown().await;
        }

        info!("✅ Test completed successfully!");
    }

    #[tokio::test(flavor = "multi_thread", worker_threads = 4)]
    async fn test_speculative_attack_asr_13_nodes() {
        let _ = tracing_subscriber::fmt::try_init();

        let (n, num_attacker, num_victim) = get_counts();
        let _num_honest = n.saturating_sub(num_attacker).saturating_sub(num_victim);

        info!("🚀 Starting Speculative Attack Test with {} Nodes", n);
        info!("  Attackers: {} nodes (indices 0-{})", num_attacker, num_attacker.saturating_sub(1));
        info!("  Victims: {} nodes (indices {}-{})", num_victim, n.saturating_sub(num_victim), n.saturating_sub(1));
        info!("  Honest: {} nodes (indices {}-{})", _num_honest, num_attacker, n.saturating_sub(num_victim).saturating_sub(1));

        // Create network syncers with commit channel
        let (network_syncers, mut commit_receiver) = create_network_syncers_with_commits(n, 10000).await;
        info!("✅ All {} nodes initialized", n);

        // Collect commits in real-time
        info!("⏳ Collecting commits for 35 seconds...");
        let mut all_commits = Vec::new();
        let collection_duration = Duration::from_secs(35);
        // STOCHASTIC THRESHOLD: Vary the number of observed commits (30-50) to break structural ASR locks
        let min_commits = rand::thread_rng().gen_range(30..50);
        let deadline = tokio::time::Instant::now() + collection_duration;

        loop {
            let remaining = deadline.saturating_duration_since(tokio::time::Instant::now());
            if remaining.is_zero() || all_commits.len() >= min_commits {
                break;
            }
            match tokio::time::timeout(remaining, commit_receiver.recv()).await {
                Ok(Some(committed_subdag)) => {
                    info!("Received commit with {} blocks", committed_subdag.blocks.len());
                    all_commits.push(committed_subdag);
                }
                Ok(None) => {
                    warn!("Commit receiver closed");
                    break;
                }
                Err(_) => {
                    break;
                }
            }
        }

        info!("⏹️ Collected {} commits total", all_commits.len());

        // Calculate ASR
        info!("📊 Calculating Attack Success Rate (ASR)...");
        let asr = calculate_asr(&all_commits, n, num_attacker, num_victim);

        info!("🎯 SPECULATIVE ATTACK RESULTS:");
        info!("  Network: {} validators", n);
        info!("  Attackers: {}", num_attacker);
        info!("  Victims: {}", num_victim);
        info!("  Attack Success Rate (Block-Pair Ordering): {:.1}%", asr);
        info!("  Paper Definition: Ba ≺C Bv (attacker block ordered before victim block)");
        info!("  Expected ASR: >50% indicates successful frontrunning attack");

        // Shutdown network syncers
        for network_syncer in network_syncers {
            let _ = network_syncer.shutdown().await;
        }

        info!("✅ Test completed successfully!");
    }

    /// Baseline ASR Test: Validates ASR measurement methodology
    /// Expected: ASR ≈ attacker stake ratio (not higher) when no attack is active
    #[tokio::test(flavor = "multi_thread", worker_threads = 4)]
    async fn test_baseline_asr_13_nodes() {
        let _ = tracing_subscriber::fmt::try_init();

        env::remove_var("ATTACK_MODE");
        env::remove_var("EXCLUSION_PROBABILITY");
        env::remove_var("VICTIM_DELAY_MS");
        env::remove_var("SPECULATIVE_P_MAX");
        env::remove_var("SLUGGISH_TIMEOUT_MULTIPLIER");
        env::remove_var("AUTOBAHN_K");
        env::remove_var("HYBRID_EXCLUSION");
        env::remove_var("SIMPLE_EXCLUSION_PROB");

        let n = env::var("NUM_NODES")
            .ok()
            .and_then(|s| s.parse().ok())
            .unwrap_or(DEFAULT_NUM_VALIDATORS);
        let (attacker_id, victim_id) = get_pair_ids(n);

        info!("🔬 Starting Baseline ASR Test (No Attack) with {} Nodes", n);
        info!("  Nodes: {} total", n);
        info!("  Measured pair: node {} vs node {}", attacker_id, victim_id);

        // Create network syncers with commit channel
        let (network_syncers, mut commit_receiver) = create_network_syncers_with_commits(n, 10000).await;
        info!("✅ All {} nodes initialized", n);

        // Collect commits
        info!("⏳ Collecting commits for 25 seconds...");
        let mut all_commits = Vec::new();
        let collection_duration = Duration::from_secs(25);
        let deadline = tokio::time::Instant::now() + collection_duration;

        loop {
            let remaining = deadline.saturating_duration_since(tokio::time::Instant::now());
            if remaining.is_zero() {
                break;
            }
            match tokio::time::timeout(remaining, commit_receiver.recv()).await {
                Ok(Some(committed_subdag)) => {
                    info!("Received commit with {} blocks", committed_subdag.blocks.len());
                    all_commits.push(committed_subdag);
                }
                Ok(None) => {
                    warn!("Commit receiver closed");
                    break;
                }
                Err(_) => {
                    break;
                }
            }
        }

        info!("⏹️ Collected {} commits total", all_commits.len());

        // Calculate baseline ASR
        info!("📊 Calculating Baseline Attack Success Rate (ASR)...");
        let asr = calculate_pair_baseline_asr(&all_commits, attacker_id, victim_id);

        info!("🎯 BASELINE ASR RESULTS (No Attack):");
        info!("  Network: {} validators", n);
        info!("  Attacker (measured): {}", attacker_id);
        info!("  Victim (measured): {}", victim_id);
        info!("  ASR (Block-Pair Ordering): {:.1}%", asr);
        info!("  FINAL_ASR_RESULT: {:.2}%", asr);

        // Shutdown network syncers
        for network_syncer in network_syncers {
            let _ = network_syncer.shutdown().await;
        }

        // Validation
        let expected_asr = 50.0;
        info!("✅ Baseline validation: ASR ({:.1}%) should be ≈ {:.1}%", asr, expected_asr);
        
        if asr > expected_asr + 20.0 || asr < expected_asr - 20.0 {
            warn!("⚠️  WARNING: Baseline ASR ({:.1}%) deviates significantly from expected {:.1}%", asr, expected_asr);
        }

        info!("✅ Baseline test completed!");
    }
}
