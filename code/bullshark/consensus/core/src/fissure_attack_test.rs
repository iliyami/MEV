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
    
    // Assert reasonable ASR
    assert!(asr > 50.0, "ASR too low: {:.1}%", asr);
    assert!(asr <= 100.0, "ASR suspiciously high: {:.1}%", asr);
    
    info!("✅ Test completed successfully!");
}

fn calculate_asr(commits: &[CommittedSubDag], num_validators: usize, num_attacker: usize, num_victim: usize) -> f64 {
    if commits.is_empty() {
        warn!("No commits to analyze");
        return 0.0;
    }
    
    // Check Attack Type
    let attack_type = std::env::var("ATTACK_TYPE").unwrap_or_else(|_| "frontrun".to_string());
    let is_backrun = attack_type == "backrun";
    let is_sandwich = attack_type == "sandwich";

    // Build global ordering
    let mut global_order = Vec::new();
    for commit in commits {
        for block in commit.blocks.iter() {
            global_order.push((block.author(), block.round(), block.reference()));
        }
    }
    
    info!("Global order contains {} blocks", global_order.len());
    
    // Identify attacker and victim blocks based on topology
    let mut attacker_positions = Vec::new();
    let mut victim_positions = Vec::new();
    
    for (pos, (author, round, _block_ref)) in global_order.iter().enumerate() {
        let author_index = author.value() as usize;

        let is_attacker_node = if is_backrun {
            // Backrun Topology: [Victim (0..V)] [Attacker (V..V+A)]
            author_index >= num_victim && author_index < (num_victim + num_attacker)
        } else if is_sandwich {
            // Sandwich Topology: [Front (0..A/2)] [Victim (A/2..V)] [Back (V..V+A/2)]
            let front_count = num_attacker / 2;
            let back_count = num_attacker - front_count;
            let back_start = front_count + num_victim;
            
            author_index < front_count || (author_index >= back_start && author_index < (back_start + back_count))
        } else {
            // Default Fissure: [Attacker (0..A)] [Honest] [Victim (N-V..N)]
            author_index < num_attacker
        };

        let is_victim_node = if is_backrun {
            author_index < num_victim
        } else if is_sandwich {
            let front_count = num_attacker / 2;
            author_index >= front_count && author_index < (front_count + num_victim)
        } else {
            author_index >= num_validators - num_victim
        };

        if is_attacker_node {
            attacker_positions.push((pos, *round));
        } else if is_victim_node {
            victim_positions.push((pos, *round));
        }
    }
    
    info!("Attacker blocks: {}", attacker_positions.len());
    info!("Victim blocks: {}", victim_positions.len());
    
    if attacker_positions.is_empty() || victim_positions.is_empty() {
        warn!("Missing attacker or victim blocks");
        return 0.0;
    }
    
    // --- Sandwich Logic ---
    if is_sandwich {
        let mut sandwiched_victims = 0;
        let mut total_victim_opportunities = 0;

        for (vic_pos, vic_round) in &victim_positions {
            total_victim_opportunities += 1;

            let has_front = attacker_positions.iter().any(|(att_pos, att_round)| *att_round == *vic_round && att_pos < vic_pos);
            let has_back = attacker_positions.iter().any(|(att_pos, att_round)| *att_round == *vic_round && att_pos > vic_pos);

            if has_front && has_back {
                sandwiched_victims += 1;
            }
        }

        let sesr = if total_victim_opportunities > 0 {
            (sandwiched_victims as f64 / total_victim_opportunities as f64) * 100.0
        } else {
            0.0
        };

        info!("SeSR calculation: {}/{} victims sandwiched = {:.1}%", sandwiched_victims, total_victim_opportunities, sesr);
        println!("FINAL_SANDWICH_STATS: {{\"sesr\": {:.2}}}", sesr);

        return sesr;
    }

    // --- Standard / Backrun ASR ---
    let mut successes = 0;
    let mut total_pairs = 0;
    
    for (att_pos, att_round) in &attacker_positions {
        for (vic_pos, vic_round) in &victim_positions {
            // Strict competition in the SAME round
            if att_round == vic_round {
                total_pairs += 1;
                
                let success = if is_backrun {
                    att_pos > vic_pos
                } else {
                    att_pos < vic_pos
                };
                
                if success {
                    successes += 1;
                }
            }
        }
    }
    
    if total_pairs == 0 {
        warn!("No comparable block pairs found in same round");
        return 0.0;
    }
    
    let asr = (successes as f64 / total_pairs as f64) * 100.0;
    info!("ASR calculation: {}/{} pairs = {:.1}%", successes, total_pairs, asr);
    
    // --- Detailed Backrun Metrics ---
    if is_backrun {
        let mut gaps = Vec::new();
        let mut l1_count = 0;
        let mut l2_count = 0;

        for (att_pos, att_round) in &attacker_positions {
            for (vic_pos, vic_round) in &victim_positions {
                if att_round == vic_round && att_pos > vic_pos {
                    let gap = att_pos - vic_pos;
                    gaps.push(gap);
                    
                    if gap == 1 {
                        l1_count += 1;
                    } else if gap == 2 || gap == 3 {
                        l2_count += 1;
                    }
                }
            }
        }

        let l1_asr = (l1_count as f64 / total_pairs as f64) * 100.0;
        let l2_asr = (l2_count as f64 / total_pairs as f64) * 100.0;

        println!(
            "FINAL_BACKRUN_STATS: {{\"l1_asr\": {:.2}, \"l2_asr\": {:.2}, \"histogram\": {:?}}}",
            l1_asr, l2_asr, gaps
        );
    }
    
    asr
}

