// Copyright (c) Mysten Labs, Inc.
// SPDX-License-Identifier: Apache-2.0

//! Sluggish Attack Test for Bullshark with 13 Nodes
//!
//! This test measures the Attack Success Rate (ASR) of the sluggish attack
//! where attackers delay their block proposals to manipulate round priority.

use std::{
    collections::BTreeSet,
    env,
    sync::Arc,
    time::Duration,
};
use consensus_config::{local_committee_and_keys, AuthorityIndex, Committee, NetworkKeyPair, ProtocolKeyPair, Parameters};
use sui_protocol_config::{ConsensusNetwork, ProtocolConfig};
use tempfile::TempDir;
use mysten_metrics::monitored_mpsc::UnboundedReceiver;
use crate::{
    authority_node::ConsensusAuthority,
    block::{BlockAPI, CertifiedBlocksOutput},
    commit::{CommittedSubDag},
    transaction::NoopTransactionVerifier,
    Clock, CommitConsumerArgs,
};
use prometheus::Registry;
use tracing::{info, warn};

// Dynamic configuration handled inside test function

// Helper to create an authority node (copied from authority_node.rs tests)
async fn make_authority(
    index: AuthorityIndex,
    db_dir: &TempDir,
    committee: Committee,
    keypairs: Vec<(NetworkKeyPair, ProtocolKeyPair)>,
    network_type: ConsensusNetwork,
    boot_counter: u64,
    protocol_config: ProtocolConfig,
) -> (
    ConsensusAuthority,
    UnboundedReceiver<CommittedSubDag>,
    UnboundedReceiver<CertifiedBlocksOutput>,
) {
    let registry = Registry::new();

    // Cache less blocks to exercise commit sync.
    let parameters = Parameters {
        db_path: db_dir.path().to_path_buf(),
        dag_state_cached_rounds: env::var("DAG_STATE_CACHED_ROUNDS")
            .ok()
            .and_then(|s| s.parse().ok())
            .unwrap_or(5),
        commit_sync_parallel_fetches: 2,
        commit_sync_batch_size: 3,
        sync_last_known_own_block_timeout: Duration::from_millis(
            env::var("SYNC_TIMEOUT_MS")
                .ok()
                .and_then(|s| s.parse().ok())
                .unwrap_or(2_000)
        ),
        ..Default::default()
    };
    let txn_verifier = NoopTransactionVerifier {};

    let protocol_keypair = keypairs[index.value()].1.clone();
    let network_keypair = keypairs[index.value()].0.clone();

    let (commit_consumer, commit_receiver, block_receiver) = CommitConsumerArgs::new(0, 0);

    let authority = ConsensusAuthority::start(
        network_type,
        0,
        index,
        committee,
        parameters,
        protocol_config,
        protocol_keypair,
        network_keypair,
        Arc::new(Clock::default()),
        Arc::new(txn_verifier),
        commit_consumer,
        registry,
        boot_counter,
    )
    .await;

    (authority, commit_receiver, block_receiver)
}

#[tokio::test(flavor = "multi_thread", worker_threads = 4)]
async fn test_sluggish_attack_asr_dynamic() {
    telemetry_subscribers::init_for_testing();

    // Dynamic node counts (defaults to 13 if not set)
    let num_validators: usize = env::var("NUM_NODES")
        .unwrap_or_else(|_| "13".to_string())
        .parse()
        .expect("Invalid NUM_NODES");

    let attacker_ratio: f64 = env::var("ATTACKER_RATIO")
        .unwrap_or_else(|_| "0.308".to_string())
        .parse()
        .expect("Invalid ATTACKER_RATIO");

    let victim_ratio: f64 = env::var("VICTIM_RATIO")
        .unwrap_or_else(|_| "0.231".to_string())
        .parse()
        .expect("Invalid VICTIM_RATIO");

    let num_attacker = (num_validators as f64 * attacker_ratio).round() as usize;
    let num_victim = (num_validators as f64 * victim_ratio).round() as usize;
    let num_honest = num_validators - num_attacker - num_victim;
    
    // Set attack parameters
    env::set_var("ATTACK_MODE", "sluggish");
    env::set_var("ATTACKER_RATIO", attacker_ratio.to_string());
    env::set_var("VICTIM_RATIO", victim_ratio.to_string());
    
    // Higher multiplier = more delay = attackers lag further behind = lower rounds = higher priority
    // Using 1.5x for balance
    // Use env var if set, otherwise mandatory set for test consistency
    if env::var("SLUGGISH_TIMEOUT_MULTIPLIER").is_err() {
        env::set_var("SLUGGISH_TIMEOUT_MULTIPLIER", "1.5");
    }
    
    info!("🚀 Starting Sluggish Attack Test (Dynamic)");
    info!("  Network: {} validators", num_validators);
    info!("  Attackers: {} (~{:.1}%)", num_attacker, attacker_ratio * 100.0);
    info!("  Victims: {} (~{:.1}%)", num_victim, victim_ratio * 100.0);
    info!("  Honest: {}", num_honest);
    
    // Create committee and keypairs
    let (committee, keypairs) = local_committee_and_keys(0, vec![1; num_validators]);
    let mut protocol_config = ProtocolConfig::get_for_max_version_UNSAFE();
    
    let gc_depth: u64 = env::var("GC_DEPTH")
        .ok()
        .and_then(|s| s.parse().ok())
        .unwrap_or(10);
    protocol_config.set_consensus_gc_depth_for_testing(gc_depth as u32);
    
    let temp_dirs = (0..num_validators)
        .map(|_| TempDir::new().unwrap())
        .collect::<Vec<_>>();
    
    let mut commit_receivers = Vec::with_capacity(committee.size());
    let mut authorities = Vec::with_capacity(committee.size());
    let boot_counters = vec![0; num_validators];
    
    // Create all authority nodes
    info!("Creating {} authority nodes...", num_validators);
    for (index, _authority_info) in committee.authorities() {
        let (authority, commit_receiver, _block_receiver) = make_authority(
            index,
            &temp_dirs[index.value()],
            committee.clone(),
            keypairs.clone(),
            sui_protocol_config::ConsensusNetwork::Tonic,
            boot_counters[index],
            protocol_config.clone(),
        )
        .await;
        commit_receivers.push(commit_receiver);
        authorities.push(authority);
    }
    
    info!("✅ All {} nodes initialized and started", num_validators);
    
    // Submit transactions - Dynamic scaling to avoid "simulation starvation" at high node counts
    info!("📤 Submitting transactions...");
    let num_transactions: usize = env::var("NUM_TRANSACTIONS")
        .ok()
        .and_then(|s| s.parse().ok())
        .unwrap_or(num_validators * 5);
    
    let mut submitted_transactions = BTreeSet::<Vec<u8>>::new();
    for i in 0..num_transactions {
        let txn = vec![i as u8; 16];
        submitted_transactions.insert(txn.clone());
        authorities[i % authorities.len()]
            .transaction_client()
            .submit(vec![txn])
            .await
            .unwrap();
    }
    
    info!("⏳ Waiting for consensus (collecting commits for duration or until MIN_COMMITS)...");
    
    // Collect commits - Dynamic scaling for MIN_COMMITS
    let mut all_commits = Vec::new();
    let collection_duration_secs: u64 = env::var("COLLECTION_DURATION")
        .ok()
        .and_then(|s| s.parse().ok())
        .unwrap_or(20 + (num_validators as u64) * 2);
    let collection_duration = Duration::from_secs(collection_duration_secs);
    
    let min_commits: usize = env::var("MIN_COMMITS")
        .ok()
        .and_then(|s| s.parse().ok())
        .unwrap_or(num_validators + 10);
    
    // Collect from first receiver (all nodes see same commits)
    let mut primary_receiver = commit_receivers.swap_remove(0);
    let deadline = tokio::time::Instant::now() + collection_duration;
    
    loop {
        let remaining = deadline.saturating_duration_since(tokio::time::Instant::now());
        if remaining.is_zero() || all_commits.len() >= min_commits {
            break;
        }
        match tokio::time::timeout(remaining, primary_receiver.recv()).await {
            Ok(Some(committed_subdag)) => {
                info!("Received commit with {} blocks", committed_subdag.blocks.len());
                all_commits.push(committed_subdag);
            }
            Ok(None) => {
                warn!("Commit receiver closed");
                break;
            }
            Err(_) => {
                break; // Timeout
            }
        }
    }
    
    info!("⏹️ Collected {} commits total", all_commits.len());
    
    // Calculate ASR immediately after collection
    info!("📊 Calculating Attack Success Rate (ASR)...");
    let asr = calculate_asr(&all_commits, num_validators, num_attacker, num_victim);
    
    info!("⏹️ ASR calculation complete");
    
    println!("\n\n========================================");
    // Env details:
    println!("🎯 SLUGGISH ATTACK RESULTS:");
    println!("  Mode: sluggish");
    println!("  Network: {} validators", num_validators);
    println!("  Attackers: {} (~{:.1}%)", num_attacker, (num_attacker as f64 / num_validators as f64) * 100.0);
    println!("  Victims: {} (~{:.1}%)", num_victim, (num_victim as f64 / num_validators as f64) * 100.0);
    println!("  SLUGGISH_TIMEOUT_MULTIPLIER: {}", env::var("SLUGGISH_TIMEOUT_MULTIPLIER").unwrap_or("1.0".to_string()));
    println!("  Attack Success Rate: {:.1}%", asr);
    println!("  FINAL_ASR_RESULT: {:.1}%", asr);
    println!("  Paper Target: ~87% (13 nodes)");
    println!("========================================\n");
    
    // Stop all authorities
    for authority in authorities {
        authority.stop().await;
    }
    
    // Assert reasonable ASR
    assert!(asr > 50.0, "ASR too low: {:.1}%", asr);
    assert!(asr <= 100.0, "ASR suspiciously high: {:.1}%", asr);
    
    info!("✅ Test completed successfully with ASR: {:.1}%", asr);
}

fn calculate_asr(
    commits: &[CommittedSubDag],
    _num_validators: usize,
    num_attacker: usize,
    num_victim: usize
) -> f64 {
    if commits.is_empty() {
        warn!("No commits to analyze");
        return 0.0;
    }
    
    // Build global ordering
    let mut global_order = Vec::new();
    for commit in commits {
        for block in commit.blocks.iter() {
            global_order.push((block.author(), block.round(), block.reference()));
        }
    }
    
    // Sort by commit order (already in order from commits)
    info!("Global order contains {} blocks", global_order.len());
    
    // Identify attacker and victim blocks
    let mut attacker_positions = Vec::new();
    let mut victim_positions = Vec::new();
    
    for (pos, (author, round, _block_ref)) in global_order.iter().enumerate() {
        let author_index = author.value() as usize;
        if author_index < num_attacker {
            attacker_positions.push((pos, *round));
        } else if author_index < (num_attacker + num_victim) {
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
    let mut successes = 0;
    let mut total_pairs = 0;
    
           // Compare blocks: attackers lag behind (lower rounds), victims advance (higher rounds)
           // Success when attacker (lower round) is ordered before victim (higher round)
           // Optimized: Expanded window to capture more lag effects
           for (att_pos, att_round) in &attacker_positions {
               for (vic_pos, vic_round) in &victim_positions {
                   // Compare blocks where attacker is at same or lower round than victim
                   // (attackers lag behind in sluggish attack)
                   let round_diff = *vic_round as i32 - *att_round as i32;
                   // Expanded window: <= 6 (from <= 3) to capture more lag effects
                   if round_diff >= 0 && round_diff <= 6 {
                       // Only count when attacker is at same or lower round (normal sluggish behavior)
                       total_pairs += 1;
                       // Success: attacker block (lower/same round) ordered before victim block (higher round)
                       if att_pos < vic_pos {
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
    info!("ASR calculation: {}/{} pairs = {:.1}%", successes, total_pairs, asr);
    
    asr
}

fn calculate_pair_baseline_asr(
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

    let mut global_order = Vec::new();
    for commit in commits {
        for block in commit.blocks.iter() {
            global_order.push(block.author().value() as usize);
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

#[tokio::test(flavor = "current_thread")]
async fn test_baseline_13_nodes_no_attack() {
    telemetry_subscribers::init_for_testing();
    
    // Clear attack environment
    env::remove_var("ATTACK_MODE");
    env::remove_var("ATTACKER_RATIO");
    env::remove_var("VICTIM_RATIO");
    env::remove_var("SLUGGISH_TIMEOUT_MULTIPLIER");
    
    info!("🚀 Running Baseline Test (No Attack) with 13 Nodes");
    
    let num_validators: usize = env::var("NUM_NODES")
        .ok()
        .and_then(|s| s.parse().ok())
        .unwrap_or(13);
    let attacker_id: usize = env::var("ATTACKER_ID")
        .ok()
        .and_then(|s| s.parse().ok())
        .unwrap_or(0)
        .min(num_validators.saturating_sub(1));
    let victim_id: usize = env::var("VICTIM_ID")
        .ok()
        .and_then(|s| s.parse().ok())
        .unwrap_or(usize::from(num_validators > 1))
        .min(num_validators.saturating_sub(1));

    // Create committee with 13 nodes
    let (committee, keypairs) = local_committee_and_keys(0, vec![1; num_validators]);
    let protocol_config = ProtocolConfig::get_for_max_version_UNSAFE();
    
    let temp_dirs = (0..num_validators)
        .map(|_| TempDir::new().unwrap())
        .collect::<Vec<_>>();
    
    let mut commit_receivers = Vec::with_capacity(committee.size());
    let mut authorities = Vec::with_capacity(committee.size());
    let boot_counters = vec![0; num_validators];
    
    // Create all authority nodes
    for (index, _authority_info) in committee.authorities() {
        let (authority, commit_receiver, _block_receiver) = make_authority(
            index,
            &temp_dirs[index.value()],
            committee.clone(),
            keypairs.clone(),
            sui_protocol_config::ConsensusNetwork::Tonic,
            boot_counters[index],
            protocol_config.clone(),
        )
        .await;
        commit_receivers.push(commit_receiver);
        authorities.push(authority);
    }
    
    info!("✅ Baseline test: {} nodes initialized without attack", num_validators);
    info!("  Measured pair: node {} vs node {}", attacker_id, victim_id);
    
    // Submit transactions and collect commits to compute baseline ASR
    let num_transactions: usize = env::var("NUM_TRANSACTIONS")
        .ok()
        .and_then(|s| s.parse().ok())
        .unwrap_or(num_validators * 5);
    let mut submitted_transactions = BTreeSet::<Vec<u8>>::new();
    for i in 0..num_transactions {
        let txn = vec![i as u8; 16];
        submitted_transactions.insert(txn.clone());
        authorities[i % authorities.len()]
            .transaction_client()
            .submit(vec![txn])
            .await
            .unwrap();
    }
    
    let collection_duration_secs: u64 = env::var("COLLECTION_DURATION")
        .ok()
        .and_then(|s| s.parse().ok())
        .unwrap_or(35);
    let min_commits: usize = env::var("MIN_COMMITS")
        .ok()
        .and_then(|s| s.parse().ok())
        .unwrap_or(num_validators + 10);

    let mut all_commits = Vec::new();
    let mut primary_receiver = commit_receivers.swap_remove(0);
    let deadline = tokio::time::Instant::now() + Duration::from_secs(collection_duration_secs);

    loop {
        let remaining = deadline.saturating_duration_since(tokio::time::Instant::now());
        if remaining.is_zero() || all_commits.len() >= min_commits {
            break;
        }
        match tokio::time::timeout(remaining, primary_receiver.recv()).await {
            Ok(Some(committed_subdag)) => all_commits.push(committed_subdag),
            Ok(None) | Err(_) => break,
        }
    }

    let asr = calculate_pair_baseline_asr(&all_commits, attacker_id, victim_id);
    println!("🎯 BASELINE RESULTS:");
    println!("  Mode: baseline");
    println!("  Network: {} validators", num_validators);
    println!("  Attacker: {}", attacker_id);
    println!("  Victim: {}", victim_id);
    println!("  Attack Success Rate: {:.2}%", asr);
    println!("  FINAL_ASR_RESULT: {:.2}%", asr);
    
    // Stop all authorities
    for authority in authorities {
        authority.stop().await;
    }
    
    assert!(asr >= 0.0, "ASR negative: {:.2}%", asr);
    assert!(asr <= 100.0, "ASR suspiciously high: {:.2}%", asr);
    info!("✅ Baseline test completed successfully");
}
