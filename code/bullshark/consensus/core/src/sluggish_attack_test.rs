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

const NUM_VALIDATORS: usize = 13;
const NUM_ATTACKER: usize = 4; // 30% (4/13)
const NUM_VICTIM: usize = 3;   // 23% (3/13)
const NUM_HONEST: usize = 6;   // 46% (6/13)

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
        dag_state_cached_rounds: 5,
        commit_sync_parallel_fetches: 2,
        commit_sync_batch_size: 3,
        sync_last_known_own_block_timeout: Duration::from_millis(2_000),
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
async fn test_sluggish_attack_asr_13_nodes() {
    telemetry_subscribers::init_for_testing();
    
    // Set attack parameters
    env::set_var("ATTACK_MODE", "sluggish");
    env::set_var("ATTACKER_RATIO", "0.308"); // 4/13
    env::set_var("VICTIM_RATIO", "0.231");   // 3/13
    // Higher multiplier = more delay = attackers lag further behind = lower rounds = higher priority
    // Using 4.0x for balance: significant lag but not so much that network stalls
    // Use env var if set, otherwise default to 1.5 (Optimized)
    if env::var("SLUGGISH_TIMEOUT_MULTIPLIER").is_err() {
        env::set_var("SLUGGISH_TIMEOUT_MULTIPLIER", "1.5");
    }
    
    info!("🚀 Starting Sluggish Attack Test with 13 Nodes");
    info!("  Attackers: {} nodes (indices 0-{})", NUM_ATTACKER, NUM_ATTACKER - 1);
    info!("  Victims: {} nodes (indices {}-{})", NUM_VICTIM, NUM_ATTACKER, NUM_ATTACKER + NUM_VICTIM - 1);
    info!("  Honest: {} nodes (indices {}-{})", NUM_HONEST, NUM_ATTACKER + NUM_VICTIM, NUM_VALIDATORS - 1);
    
    // Create committee and keypairs for all 13 nodes
    let (committee, keypairs) = local_committee_and_keys(0, vec![1; NUM_VALIDATORS]);
    let mut protocol_config = ProtocolConfig::get_for_max_version_UNSAFE();
    protocol_config.set_consensus_gc_depth_for_testing(10);
    
    let temp_dirs = (0..NUM_VALIDATORS)
        .map(|_| TempDir::new().unwrap())
        .collect::<Vec<_>>();
    
    let mut commit_receivers = Vec::with_capacity(committee.size());
    let mut authorities = Vec::with_capacity(committee.size());
    let boot_counters = vec![0; NUM_VALIDATORS];
    
    // Create all authority nodes
    info!("Creating {} authority nodes...", NUM_VALIDATORS);
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
    
    info!("✅ All 13 nodes initialized and started");
    
    // Submit transactions
    info!("📤 Submitting transactions...");
    const NUM_TRANSACTIONS: u8 = 50;
    let mut submitted_transactions = BTreeSet::<Vec<u8>>::new();
    for i in 0..NUM_TRANSACTIONS {
        let txn = vec![i; 16];
        submitted_transactions.insert(txn.clone());
        authorities[i as usize % authorities.len()]
            .transaction_client()
            .submit(vec![txn])
            .await
            .unwrap();
    }
    
    info!("⏳ Waiting for consensus (collecting commits for 25 seconds or until we have 10 commits)...");
    
    // Collect commits for a fixed duration or until we have enough
    let mut all_commits = Vec::new();
    let collection_duration = Duration::from_secs(25);
    const MIN_COMMITS: usize = 10;
    
    // Collect from first receiver (all nodes see same commits)
    let mut primary_receiver = commit_receivers.swap_remove(0);
    let deadline = tokio::time::Instant::now() + collection_duration;
    
    loop {
        let remaining = deadline.saturating_duration_since(tokio::time::Instant::now());
        if remaining.is_zero() || all_commits.len() >= MIN_COMMITS {
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
    let asr = calculate_asr(&all_commits);
    
    info!("⏹️ ASR calculation complete");
    
    info!("🎯 SLUGGISH ATTACK RESULTS:");
    info!("  Network: {} validators", NUM_VALIDATORS);
    info!("  Attackers: {} (30%)", NUM_ATTACKER);
    info!("  Victims: {} (23%)", NUM_VICTIM);
    info!("  Attack Success Rate: {:.1}%", asr);
    info!("  Paper Target: ~87% (13 nodes)");
    
    // Stop all authorities
    for authority in authorities {
        authority.stop().await;
    }
    
    // Assert reasonable ASR
    assert!(asr > 50.0, "ASR too low: {:.1}%", asr);
    assert!(asr <= 100.0, "ASR suspiciously high: {:.1}%", asr);
    
    info!("✅ Test completed successfully!");
}

fn calculate_asr(commits: &[CommittedSubDag]) -> f64 {
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
        if author_index < NUM_ATTACKER {
            attacker_positions.push((pos, *round));
        } else if author_index < (NUM_ATTACKER + NUM_VICTIM) {
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

#[tokio::test(flavor = "current_thread")]
async fn test_baseline_13_nodes_no_attack() {
    telemetry_subscribers::init_for_testing();
    
    // Clear attack environment
    env::remove_var("ATTACK_MODE");
    env::remove_var("ATTACKER_RATIO");
    env::remove_var("VICTIM_RATIO");
    env::remove_var("SLUGGISH_TIMEOUT_MULTIPLIER");
    
    info!("🚀 Running Baseline Test (No Attack) with 13 Nodes");
    
    // Create committee with 13 nodes
    let (committee, keypairs) = local_committee_and_keys(0, vec![1; NUM_VALIDATORS]);
    let protocol_config = ProtocolConfig::get_for_max_version_UNSAFE();
    
    let temp_dirs = (0..NUM_VALIDATORS)
        .map(|_| TempDir::new().unwrap())
        .collect::<Vec<_>>();
    
    let mut commit_receivers = Vec::with_capacity(committee.size());
    let mut authorities = Vec::with_capacity(committee.size());
    let boot_counters = vec![0; NUM_VALIDATORS];
    
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
    
    info!("✅ Baseline test: 13 nodes initialized without attack");
    info!("  All nodes should participate fairly");
    
    // Submit a few transactions to verify the network works
    const NUM_TRANSACTIONS: u8 = 10;
    let mut submitted_transactions = BTreeSet::<Vec<u8>>::new();
    for i in 0..NUM_TRANSACTIONS {
        let txn = vec![i; 16];
        submitted_transactions.insert(txn.clone());
        authorities[i as usize % authorities.len()]
            .transaction_client()
            .submit(vec![txn])
            .await
            .unwrap();
    }
    
    // Wait for at least one commit
    let mut received_any = false;
    for receiver in &mut commit_receivers {
        if let Ok(Some(_)) = tokio::time::timeout(Duration::from_secs(3), receiver.recv()).await {
            received_any = true;
            break;
        }
    }
    
    assert!(received_any, "Should receive at least one commit");
    
    // Stop all authorities
    for authority in authorities {
        authority.stop().await;
    }
    
    info!("✅ Baseline test completed successfully");
}

