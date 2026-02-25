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
    
    println!("\n\n========================================");
    // Env details:
    println!("🎯 SLUGGISH ATTACK RESULTS:");
    println!("  Mode: sluggish");
    println!("  Type: {}", env::var("ATTACK_TYPE").unwrap_or_else(|_| "frontrun".to_string()));
    println!("  Network: {} validators", num_validators);
    println!("  Attackers: {} (~{:.1}%)", num_attacker, (num_attacker as f64 / num_validators as f64) * 100.0);
    println!("  Victims: {} (~{:.1}%)", num_victim, (num_victim as f64 / num_validators as f64) * 100.0);
    println!("  SLUGGISH_TIMEOUT_MULTIPLIER: {}", env::var("SLUGGISH_TIMEOUT_MULTIPLIER").unwrap_or_else(|_| "1.0".to_string()));
    
    // Detailed metrics will be printed by calculate_asr
    let asr = calculate_asr(&all_commits, num_validators, num_attacker, num_victim);
    
    println!("  FINAL_ASR_RESULT: {:.1}%", asr);
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
            // Default Sluggish: [Attacker (0..A)] [Honest] [Victim (N-V..N)]
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
    
    // Metrics
    let mut successes = 0;
    let mut total_pairs = 0;
    
    // Backrunning metrics
    let mut l1_successes = 0;
    let mut l2_successes = 0;
    let mut lx_successes = 0;
    let mut backrun_total = 0;
    let mut backrun_hist = vec![0; 11];

    // Sandwich metrics
    let mut victims_sandwiched = 0;
    let mut total_victims_for_sandwich = 0;

    // ASR-F / ASR-B Logic
    for (att_pos, att_round) in &attacker_positions {
        for (vic_pos, vic_round) in &victim_positions {
            // Compare blocks in a window
            // Sluggish specific: Attacker might lag by several rounds (window=6)
            let round_diff = (*vic_round as i32 - *att_round as i32).abs();
            if round_diff <= 6 {
                total_pairs += 1;
                
                let success = if is_backrun || is_sandwich {
                    *att_pos > *vic_pos
                } else {
                    *att_pos < *vic_pos
                };
                
                if success {
                    successes += 1;
                }
            }
        }
    }

    // Granular Backrun Analysis (L1, L2, LX)
    if is_backrun || is_sandwich {
        for (vic_pos, vic_round) in &victim_positions {
            backrun_total += 1;
            let mut found_backrun = false;
            
            // Look for closest attacker AFTER victim
            for (att_pos, att_round) in &attacker_positions {
                if *att_pos > *vic_pos {
                    let dist = *att_pos - *vic_pos;
                    let r_diff = (*att_round as i32 - *vic_round as i32).abs();
                    
                    if r_diff <= 3 { // Tighter window for "direct" backrun
                        found_backrun = true;
                        lx_successes += 1;
                        if dist == 1 { l1_successes += 1; }
                        if dist == 2 { l2_successes += 1; }
                        
                        let hist_idx = dist.min(10);
                        backrun_hist[hist_idx] += 1;
                        break;
                    }
                }
            }
        }
    }

    // Sandwich Analysis (SeSR)
    if is_sandwich {
        let front_count = num_attacker / 2;
        let back_start = front_count + num_victim;

        for (vic_pos, vic_round) in &victim_positions {
            total_victims_for_sandwich += 1;
            let mut has_front = false;
            let mut has_back = false;

            // Find Frontrun
            for (att_pos, att_author_ref) in global_order.iter().enumerate() {
                let author_idx = att_author_ref.0.value() as usize;
                let round = att_author_ref.1;
                if author_idx < front_count && att_pos < *vic_pos && (round as i32 - *vic_round as i32).abs() <= 3 {
                    has_front = true;
                    break;
                }
            }

            // Find Backrun
            for (att_pos, att_author_ref) in global_order.iter().enumerate() {
                let author_idx = att_author_ref.0.value() as usize;
                let round = att_author_ref.1;
                if author_idx >= back_start && att_pos > *vic_pos && (round as i32 - *vic_round as i32).abs() <= 3 {
                    has_back = true;
                    break;
                }
            }

            if has_front && has_back {
                victims_sandwiched += 1;
            }
        }
    }

    let asr = (successes as f64 / total_pairs as f64) * 100.0;
    
    if is_backrun {
        let l1 = (l1_successes as f64 / backrun_total as f64) * 100.0;
        let l2 = (l2_successes as f64 / backrun_total as f64) * 100.0;
        let lx = (lx_successes as f64 / backrun_total as f64) * 100.0;
        println!("  ASR-B (Overall): {:.1}%", asr);
        println!("  L1 Success: {:.1}% ({}/{})", l1, l1_successes, backrun_total);
        println!("  L2 Success: {:.1}% ({}/{})", l2, l2_successes, backrun_total);
        println!("  LX Success: {:.1}% ({}/{})", lx, lx_successes, backrun_total);
        println!("  Backrun Histogram (Gap 1-10): {:?}", &backrun_hist[1..]);
        return lx; // Use LX as the final result for backrunning
    }

    if is_sandwich {
        let sesr = (victims_sandwiched as f64 / total_victims_for_sandwich as f64) * 100.0;
        println!("  ASR-S (Precedence): {:.1}%", asr);
        println!("  Sandwich Efficiency (SeSR): {:.1}% ({}/{})", sesr, victims_sandwiched, total_victims_for_sandwich);
        return sesr; // Use SeSR as the final result for sandwiching
    }

    println!("  ASR-F (Frontrun): {:.1}%", asr);
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
    
    const NUM_VALIDATORS: usize = 13;
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

