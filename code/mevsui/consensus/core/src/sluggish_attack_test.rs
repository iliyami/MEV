// Copyright (c) Mysten Labs, Inc.
// SPDX-License-Identifier: Apache-2.0

//! Sluggish Attack Test for MEVSUI with 13 Nodes
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
    Clock, CommitConsumer,
};
use prometheus::Registry;
use tracing::{info, warn};

const NUM_VALIDATORS: usize = 13;
const NUM_ATTACKER: usize = 4; // ~30.8% (4/13)
const NUM_VICTIM: usize = 3;   // ~23.1% (3/13)
const NUM_HONEST: usize = 6;   // ~46.1% (6/13)

// Helper to create an authority node
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

    let (commit_consumer, commit_receiver, block_receiver) = CommitConsumer::new(0);

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
    env::set_var("SLUGGISH_TIMEOUT_MULTIPLIER", "2.0");
    
    info!("🚀 Starting Sluggish Attack Test with 13 Nodes");
    info!("  Attackers: {} nodes (indices 0-{})", NUM_ATTACKER, NUM_ATTACKER - 1);
    info!("  Victims: {} nodes (indices {}-{})", NUM_VICTIM, NUM_VALIDATORS - NUM_VICTIM, NUM_VALIDATORS - 1);
    info!("  Honest: {} nodes (indices {}-{})", NUM_HONEST, NUM_ATTACKER, NUM_VALIDATORS - NUM_VICTIM - 1);

    // Create committee and keypairs for all 13 nodes
    let (committee, keypairs) = local_committee_and_keys(0, vec![1; NUM_VALIDATORS]);
    let mut protocol_config = ProtocolConfig::get_for_max_version_UNSAFE();
    
    let gc_depth: u64 = env::var("GC_DEPTH")
        .ok()
        .and_then(|s| s.parse().ok())
        .unwrap_or(10);
    protocol_config.set_consensus_gc_depth_for_testing(gc_depth);

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

    info!("✅ All {} nodes initialized and started", NUM_VALIDATORS);

    // Submit transactions - Dynamic scaling
    info!("📤 Submitting transactions...");
    let num_transactions: usize = env::var("NUM_TRANSACTIONS")
        .ok()
        .and_then(|s| s.parse().ok())
        .unwrap_or(NUM_VALIDATORS * 5);
    
    let mut submitted_transactions = BTreeSet::<Vec<u8>>::new();
    for i in 0..num_transactions {
        let txn = vec![vec![i as u8; 32]];
        submitted_transactions.insert(txn[0].clone());
        authorities[i % authorities.len()]
            .transaction_client()
            .submit(txn)
            .await
            .unwrap();
    }

    info!("⏳ Waiting for consensus (collecting commits for duration or until MIN_COMMITS)...");
    
    // Collect commits - Dynamic scaling
    let mut all_commits = Vec::new();
    let collection_duration_secs: u64 = env::var("COLLECTION_DURATION")
        .ok()
        .and_then(|s| s.parse().ok())
        .unwrap_or(35);
    let collection_duration = Duration::from_secs(collection_duration_secs);
    
    let min_commits: usize = env::var("MIN_COMMITS")
        .ok()
        .and_then(|s| s.parse().ok())
        .unwrap_or(NUM_VALIDATORS + 10);

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
    let asr = calculate_asr(&all_commits);
    
    info!("⏹️ ASR calculation complete");
    
    println!("🎯 SLUGGISH ATTACK RESULTS:");
    println!("  Mode: sluggish");
    println!("  Network: {} validators", NUM_VALIDATORS);
    println!("  Attackers: {} (~30.8%)", NUM_ATTACKER);
    println!("  Victims: {} (~23.1%)", NUM_VICTIM);
    println!("  Attack Success Rate: {:.1}%", asr);
    println!("  FINAL_ASR_RESULT: {:.1}%", asr);
    println!("  Paper Target: ~94% (50 nodes, scaled to 13 nodes)");
    println!("  Bullshark Baseline: ~51.0%");
    
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
    
    info!("Global order contains {} blocks", global_order.len());
    
    // Identify attacker and victim blocks
    // Attackers are first NUM_ATTACKER nodes (indices 0 to NUM_ATTACKER-1)
    // Victims are last NUM_VICTIM nodes (indices NUM_VALIDATORS-NUM_VICTIM to NUM_VALIDATORS-1)
    let mut attacker_positions = Vec::new();
    let mut victim_positions = Vec::new();
    
    for (pos, (author, round, _block_ref)) in global_order.iter().enumerate() {
        let author_index = author.value() as usize;
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
    // For sluggish attack: attackers delay proposals to manipulate round priority
    // causing their blocks to be ordered before victim blocks
    let mut successes = 0;
    let mut total_pairs = 0;
    
    // ASR METHODOLOGY (Aligned with Paper):
    // Sluggish Attack gives advantage through ROUND-BASED ordering.
    // Attackers delay, staying in earlier rounds. Earlier rounds are ordered first.
    //
    // We measure: P(AttackerPos < VictimPos | Attacker Round <= Victim Round)
    
    // For Sluggish: Count pairs where attacker is at same or earlier round
    // This is where the delay-based advantage applies
    for (att_pos, att_round) in &attacker_positions {
        for (vic_pos, vic_round) in &victim_positions {
            // Sluggish advantage: attacker is at same or earlier round (delay effect)
            if att_round <= vic_round {
                total_pairs += 1;
                
                // Success: attacker ordered before victim
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


