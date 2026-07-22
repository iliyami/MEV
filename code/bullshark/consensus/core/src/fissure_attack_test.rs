// Copyright (c) Mysten Labs, Inc.
// SPDX-License-Identifier: Apache-2.0

//! Fissure Attack Test for Bullshark with 13 Nodes
//!
//! This test measures the Attack Success Rate (ASR) of the fissure attack
//! where attackers exclude victim blocks from their parent sets.

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
    mev_attack_metrics::calculate_attack_score,
    transaction::NoopTransactionVerifier,
    Clock, CommitConsumerArgs,
};
use prometheus::Registry;
use tracing::{info, warn};

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
async fn test_fissure_attack_asr_dynamic() {
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

    env::set_var("ATTACK_MODE", "fissure");
    // Ensure ratios are set for other components checking env vars
    env::set_var("ATTACKER_RATIO", attacker_ratio.to_string());
    env::set_var("VICTIM_RATIO", victim_ratio.to_string());
    
    info!("🚀 Starting Fissure Attack Test with {} Nodes", num_validators);
    info!("  Attackers: {} nodes (indices 0-{})", num_attacker, num_attacker.saturating_sub(1));
    info!("  Victims: {} nodes (indices {}-{})", num_victim, num_validators - num_victim, num_validators - 1);
    info!("  Honest: {} nodes (indices {}-{})", num_honest, num_attacker, num_validators - num_victim - 1);

    // Create committee and keypairs.
    // D2 (skewed stake): env-gated stake vector (comma-separated, one per
    // validator). Config-only — the committee builder already accepts arbitrary
    // stake and leader election is stake-weighted; BFT validity (attacker total
    // < 1/3) is enforced by the driver that builds STAKE_PROFILE.
    let stake_vector: Vec<u64> = std::env::var("STAKE_PROFILE")
        .ok()
        .map(|s| s.split(',').filter_map(|x| x.trim().parse::<u64>().ok()).collect::<Vec<u64>>())
        .filter(|v| v.len() == num_validators && v.iter().all(|&s| s > 0))
        .unwrap_or_else(|| vec![1; num_validators]);
    let (committee, keypairs) = local_committee_and_keys(0, stake_vector);
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
        let txn = vec![vec![i as u8; 32]];
        submitted_transactions.insert(txn[0].clone());
        authorities[i % authorities.len()]
            .transaction_client()
            .submit(txn)
            .await
            .unwrap();
    }

    info!("⏳ Waiting for consensus (collecting commits for duration or until MIN_COMMITS)...");
    
    // Collect commits - Dynamic scaling for MIN_COMMITS
    let mut all_commits = Vec::new();
    let collection_duration_secs: u64 = env::var("COLLECTION_DURATION")
        .ok()
        .and_then(|s| s.parse().ok())
        .unwrap_or(35);
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
    
    println!("🎯 FISSURE ATTACK RESULTS:");
    println!("  Mode: fissure");
    println!("  Network: {} validators", num_validators);
    println!("  Attackers: {} (~{:.1}%)", num_attacker, attacker_ratio * 100.0);
    println!("  Victims: {} (~{:.1}%)", num_victim, victim_ratio * 100.0);
    println!("  Attack Success Rate: {:.1}%", asr);
    println!("  FINAL_ASR_RESULT: {:.1}%", asr);
    println!("  Paper Target: ~94% (50 nodes)");
    
    // Stop all authorities
    for authority in authorities {
        authority.stop().await;
    }
    
    let attack_type = env::var("ATTACK_TYPE").unwrap_or_else(|_| "frontrun".to_string());
    if attack_type == "frontrun" {
        assert!(asr > 50.0, "ASR too low: {:.1}%", asr);
    } else {
        assert!(asr >= 0.0, "ASR negative: {:.1}%", asr);
    }
    assert!(asr <= 100.0, "ASR suspiciously high: {:.1}%", asr);
    
    info!("✅ Test completed successfully!");
}

fn calculate_asr(commits: &[CommittedSubDag], num_validators: usize, num_attacker: usize, num_victim: usize) -> f64 {
    calculate_attack_score(commits, num_validators, num_attacker, num_victim)
}
