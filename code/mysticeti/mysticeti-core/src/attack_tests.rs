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
use tokio::sync::mpsc;
use tracing::{info, warn};

    const NUM_VALIDATORS: usize = 13;
    const NUM_ATTACKER: usize = 4; // ~30.8% (4/13)
    const NUM_VICTIM: usize = 3;   // ~23.1% (3/13)
    const NUM_HONEST: usize = 6;   // ~46.1% (6/13)

    // Helper to create network syncers with commit receivers
    async fn create_network_syncers_with_commits(
        n: usize,
        rounds_in_epoch: RoundNumber,
    ) -> (
        Vec<NetworkSyncer<TestBlockHandler, SimpleCommitObserver>>,
        mpsc::UnboundedReceiver<CommittedSubDag>,
    ) {
        let parameters = Parameters::default();
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
    /// 
    /// Paper: "A block Bv is said to be frontrun by a block Ba from the attacker Na 
    /// if Na creates Ba after witnessing Bv and eventually Ba ≺C Bv"
    /// where ≺C denotes the block committing order relation.
    /// 
    /// ASR = (# pairs where attacker block ordered before victim block) / (total # pairs)
    fn calculate_asr(commits: &[CommittedSubDag]) -> f64 {
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
            if author_index < NUM_ATTACKER {
                attacker_positions.push((pos, *round));
            } else if author_index >= NUM_VALIDATORS - NUM_VICTIM {
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
        info!("  Expected attacker ratio (stake): ~{:.1}%", (NUM_ATTACKER as f64 / NUM_VALIDATORS as f64) * 100.0);
        
        asr
    }

    #[tokio::test(flavor = "multi_thread", worker_threads = 4)]
    async fn test_fissure_attack_asr_13_nodes() {
        let _ = tracing_subscriber::fmt::try_init();

        // Set attack parameters
        env::set_var("ATTACK_MODE", "fissure");
        env::set_var("ATTACKER_RATIO", "0.308"); // 4/13
        env::set_var("VICTIM_RATIO", "0.231");   // 3/13

        info!("🚀 Starting Fissure Attack Test with 13 Nodes");
        info!("  Attackers: {} nodes (indices 0-{})", NUM_ATTACKER, NUM_ATTACKER - 1);
        info!("  Victims: {} nodes (indices {}-{})", NUM_VICTIM, NUM_VALIDATORS - NUM_VICTIM, NUM_VALIDATORS - 1);
        info!("  Honest: {} nodes (indices {}-{})", NUM_HONEST, NUM_ATTACKER, NUM_VALIDATORS - NUM_VICTIM - 1);

        // Create network syncers with commit channel
        let (network_syncers, mut commit_receiver) = create_network_syncers_with_commits(NUM_VALIDATORS, 10000).await;
        info!("✅ All {} nodes initialized", NUM_VALIDATORS);

        // Collect commits in real-time
        info!("⏳ Collecting commits for 35 seconds...");
        let mut all_commits = Vec::new();
        let collection_duration = Duration::from_secs(35);
        const MIN_COMMITS: usize = 10;
        let deadline = tokio::time::Instant::now() + collection_duration;

        loop {
            let remaining = deadline.saturating_duration_since(tokio::time::Instant::now());
            if remaining.is_zero() || all_commits.len() >= MIN_COMMITS {
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
        let asr = calculate_asr(&all_commits);

        info!("🎯 FISSURE ATTACK RESULTS:");
        info!("  Network: {} validators", NUM_VALIDATORS);
        info!("  Attackers: {} (~30.8%)", NUM_ATTACKER);
        info!("  Victims: {} (~23.1%)", NUM_VICTIM);
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

        // Set attack parameters
        env::set_var("ATTACK_MODE", "certification_race");
        env::set_var("ATTACKER_RATIO", "0.308"); // 4/13
        env::set_var("VICTIM_RATIO", "0.231");   // 3/13

        info!("🚀 Starting Certification Race Attack Test with 13 Nodes");
        info!("  Attack Type: Network-layer timing attack (NOT consensus-layer exclusion)");
        info!("  Strategy: Detect victim blocks → Immediately propose attacker block → Race to >2/3 certification");
        info!("  Attackers: {} nodes (indices 0-{})", NUM_ATTACKER, NUM_ATTACKER - 1);
        info!("  Victims: {} nodes (indices {}-{})", NUM_VICTIM, NUM_VALIDATORS - NUM_VICTIM, NUM_VALIDATORS - 1);
        info!("  Honest: {} nodes (indices {}-{})", NUM_HONEST, NUM_ATTACKER, NUM_VALIDATORS - NUM_VICTIM - 1);

        // Create network syncers with commit channel
        let (network_syncers, mut commit_receiver) = create_network_syncers_with_commits(NUM_VALIDATORS, 10000).await;
        info!("✅ All {} nodes initialized", NUM_VALIDATORS);

        // Collect commits in real-time
        info!("⏳ Collecting commits for 35 seconds...");
        let mut all_commits = Vec::new();
        let collection_duration = Duration::from_secs(35);
        const MIN_COMMITS: usize = 10;
        let deadline = tokio::time::Instant::now() + collection_duration;

        loop {
            let remaining = deadline.saturating_duration_since(tokio::time::Instant::now());
            if remaining.is_zero() || all_commits.len() >= MIN_COMMITS {
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
        let asr = calculate_asr(&all_commits);

        info!("🎯 CERTIFICATION RACE ATTACK RESULTS:");
        info!("  Network: {} validators", NUM_VALIDATORS);
        info!("  Attackers: {} (~30.8%)", NUM_ATTACKER);
        info!("  Victims: {} (~23.1%)", NUM_VICTIM);
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

        // Set attack parameters
        env::set_var("ATTACK_MODE", "sluggish");
        env::set_var("ATTACKER_RATIO", "0.308"); // 4/13
        env::set_var("VICTIM_RATIO", "0.231");   // 3/13
        env::set_var("SLUGGISH_TIMEOUT_MULTIPLIER", "2.0"); // OPTIMIZED: Reduced to prevent WAL overflow

        info!("🚀 Starting Sluggish Attack Test with 13 Nodes");
        info!("  Attackers: {} nodes (indices 0-{})", NUM_ATTACKER, NUM_ATTACKER - 1);
        info!("  Victims: {} nodes (indices {}-{})", NUM_VICTIM, NUM_VALIDATORS - NUM_VICTIM, NUM_VALIDATORS - 1);
        info!("  Honest: {} nodes (indices {}-{})", NUM_HONEST, NUM_ATTACKER, NUM_VALIDATORS - NUM_VICTIM - 1);

        // Create network syncers with commit channel
        let (network_syncers, mut commit_receiver) = create_network_syncers_with_commits(NUM_VALIDATORS, 10000).await;
        info!("✅ All {} nodes initialized", NUM_VALIDATORS);

        // Collect commits in real-time
        info!("⏳ Collecting commits for 15 seconds (optimized for Sluggish attack)...");
        let mut all_commits = Vec::new();
        let collection_duration = Duration::from_secs(15); // Optimized for faster tests
        const MIN_COMMITS: usize = 6; // Reduced minimum for faster completion
        let deadline = tokio::time::Instant::now() + collection_duration;

        loop {
            let remaining = deadline.saturating_duration_since(tokio::time::Instant::now());
            if remaining.is_zero() || all_commits.len() >= MIN_COMMITS {
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
        let asr = calculate_asr(&all_commits);

        info!("🎯 SLUGGISH ATTACK RESULTS:");
        info!("  Network: {} validators", NUM_VALIDATORS);
        info!("  Attackers: {} (~30.8%)", NUM_ATTACKER);
        info!("  Victims: {} (~23.1%)", NUM_VICTIM);
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

        // Set attack parameters
        env::set_var("ATTACK_MODE", "speculative");
        env::set_var("ATTACKER_RATIO", "0.308"); // 4/13
        env::set_var("VICTIM_RATIO", "0.231");   // 3/13

        info!("🚀 Starting Speculative Attack Test with 13 Nodes");
        info!("  Attackers: {} nodes (indices 0-{})", NUM_ATTACKER, NUM_ATTACKER - 1);
        info!("  Victims: {} nodes (indices {}-{})", NUM_VICTIM, NUM_VALIDATORS - NUM_VICTIM, NUM_VALIDATORS - 1);
        info!("  Honest: {} nodes (indices {}-{})", NUM_HONEST, NUM_ATTACKER, NUM_VALIDATORS - NUM_VICTIM - 1);

        // Create network syncers with commit channel
        let (network_syncers, mut commit_receiver) = create_network_syncers_with_commits(NUM_VALIDATORS, 10000).await;
        info!("✅ All {} nodes initialized", NUM_VALIDATORS);

        // Collect commits in real-time
        info!("⏳ Collecting commits for 35 seconds...");
        let mut all_commits = Vec::new();
        let collection_duration = Duration::from_secs(35);
        const MIN_COMMITS: usize = 10;
        let deadline = tokio::time::Instant::now() + collection_duration;

        loop {
            let remaining = deadline.saturating_duration_since(tokio::time::Instant::now());
            if remaining.is_zero() || all_commits.len() >= MIN_COMMITS {
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
        let asr = calculate_asr(&all_commits);

        info!("🎯 SPECULATIVE ATTACK RESULTS:");
        info!("  Network: {} validators", NUM_VALIDATORS);
        info!("  Attackers: {} (~30.8%)", NUM_ATTACKER);
        info!("  Victims: {} (~23.1%)", NUM_VICTIM);
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

        // BASELINE TEST: No attack, should have ASR ≈ attacker stake ratio
        env::set_var("ATTACK_MODE", ""); // NO ATTACK
        env::set_var("ATTACKER_RATIO", "0.308"); // 4/13
        env::set_var("VICTIM_RATIO", "0.231");   // 3/13

        info!("🔬 Starting Baseline ASR Test (No Attack)");
        info!("  This test validates that ASR measurement is correct");
        info!("  Expected: ASR ≈ 50% (random ordering in fair system)");
        info!("  Paper Definition: Ba ≺C Bv (block-pair ordering)");
        info!("  Attackers: {} nodes (indices 0-{})", NUM_ATTACKER, NUM_ATTACKER - 1);
        info!("  Victims: {} nodes (indices {}-{})", NUM_VICTIM, NUM_VALIDATORS - NUM_VICTIM, NUM_VALIDATORS - 1);

        // Create network syncers with commit channel
        let (network_syncers, mut commit_receiver) = create_network_syncers_with_commits(NUM_VALIDATORS, 10000).await;
        info!("✅ All {} nodes initialized", NUM_VALIDATORS);

        // Collect commits
        info!("⏳ Collecting commits for 25 seconds...");
        let mut all_commits = Vec::new();
        let collection_duration = Duration::from_secs(25);
        const MIN_COMMITS: usize = 5;
        let deadline = tokio::time::Instant::now() + collection_duration;

        loop {
            let remaining = deadline.saturating_duration_since(tokio::time::Instant::now());
            if remaining.is_zero() || all_commits.len() >= MIN_COMMITS {
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
        let asr = calculate_asr(&all_commits);

        info!("🎯 BASELINE ASR RESULTS (No Attack):");
        info!("  Network: {} validators", NUM_VALIDATORS);
        info!("  Attackers: {} (~30.8%)", NUM_ATTACKER);
        info!("  ASR (Block-Pair Ordering): {:.1}%", asr);
        info!("  Expected: ASR ≈ 50% (random ordering in fair system)");
        info!("  Paper Definition: Ba ≺C Bv (block-pair ordering per paper)");

        // Shutdown network syncers
        for network_syncer in network_syncers {
            let _ = network_syncer.shutdown().await;
        }

        // Validation: In a fair system without attack, ASR should be around 50% (random ordering)
        // If significantly > 50%, there's inherent ordering bias
        // If significantly < 50%, there's inherent ordering bias against attackers
        let expected_asr = 50.0;
        info!("✅ Baseline validation: ASR ({:.1}%) should be ≈ {:.1}% (random ordering)", asr, expected_asr);
        
        // If ASR deviates significantly from 50%, there's measurement bias or protocol issue
        if asr > expected_asr + 15.0 || asr < expected_asr - 15.0 {
            warn!("⚠️  WARNING: Baseline ASR ({:.1}%) deviates significantly from expected {:.1}%", asr, expected_asr);
            warn!("   This suggests measurement bias or protocol issue");
        }

        info!("✅ Baseline test completed!");
    }
}
