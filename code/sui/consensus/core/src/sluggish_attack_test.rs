// Copyright (c) Mysten Labs, Inc.
// SPDX-License-Identifier: Apache-2.0

//! Sluggish attack ASR test (paper-1 port to upstream Sui).
//!
//! Requires SLUGGISH_TIMEOUT_MULTIPLIER. Attackers delay their block
//! proposal by that multiple of leader_timeout, causing them to fall
//! behind on round positioning.

use std::{collections::BTreeSet, env, sync::Arc, time::Duration};

use consensus_config::{
    AuthorityIndex, Committee, ConsensusProtocolConfig, NetworkKeyPair, Parameters,
    ProtocolKeyPair, local_committee_and_keys,
};
use mysten_metrics::monitored_mpsc::UnboundedReceiver;
use prometheus::Registry;
use tempfile::TempDir;
use tracing::{info, warn};

use crate::{
    CommitConsumerArgs, Clock,
    authority_node::ConsensusAuthority,
    block::BlockAPI,
    commit::CommittedSubDag,
    transaction::NoopTransactionVerifier,
};

async fn make_authority(
    index: AuthorityIndex,
    db_dir: &TempDir,
    committee: Committee,
    keypairs: Vec<(NetworkKeyPair, ProtocolKeyPair)>,
    boot_counter: u64,
    protocol_config: ConsensusProtocolConfig,
) -> (ConsensusAuthority, UnboundedReceiver<CommittedSubDag>) {
    let registry = Registry::new();
    let parameters = Parameters {
        db_path: db_dir.path().to_path_buf(),
        dag_state_cached_rounds: 5,
        commit_sync_parallel_fetches: 2,
        commit_sync_batch_size: 3,
        sync_last_known_own_block_timeout: Duration::from_millis(2_000),
        ..Default::default()
    };
    let protocol_keypair = keypairs[index.value()].1.clone();
    let network_keypair = keypairs[index.value()].0.clone();
    let (commit_consumer, commit_receiver) = CommitConsumerArgs::new(0, 0);
    let authority = ConsensusAuthority::start(
        crate::authority_node::NetworkType::Tonic,
        0,
        committee,
        parameters,
        protocol_config,
        Some(protocol_keypair),
        network_keypair,
        Arc::new(Clock::default()),
        Arc::new(NoopTransactionVerifier {}),
        commit_consumer,
        registry,
        boot_counter,
    )
    .await;
    (authority, commit_receiver)
}

#[tokio::test(flavor = "multi_thread", worker_threads = 4)]
async fn test_sluggish_attack_asr_dynamic() {
    telemetry_subscribers::init_for_testing();

    let num_validators: usize = env::var("NUM_NODES")
        .ok()
        .and_then(|s| s.parse().ok())
        .unwrap_or(13);
    let attacker_ratio: f64 = env::var("ATTACKER_RATIO")
        .ok()
        .and_then(|s| s.parse().ok())
        .unwrap_or(0.308);
    let victim_ratio: f64 = env::var("VICTIM_RATIO")
        .ok()
        .and_then(|s| s.parse().ok())
        .unwrap_or(0.231);
    let multiplier: f64 = env::var("SLUGGISH_TIMEOUT_MULTIPLIER")
        .ok()
        .and_then(|s| s.parse().ok())
        .unwrap_or(2.0);

    let num_attacker = (num_validators as f64 * attacker_ratio).round() as usize;
    let num_victim = (num_validators as f64 * victim_ratio).round() as usize;

    // SAFETY: set before any ConsensusAuthority spawns.
    unsafe {
        env::set_var("ATTACK_MODE", "sluggish");
        env::set_var("ATTACKER_RATIO", attacker_ratio.to_string());
        env::set_var("VICTIM_RATIO", victim_ratio.to_string());
        env::set_var("SLUGGISH_TIMEOUT_MULTIPLIER", multiplier.to_string());
    }

    info!(
        "Sluggish attack ASR test: n={num_validators} attackers={num_attacker} victims={num_victim} mult={multiplier}"
    );

    let (committee, keypairs) = local_committee_and_keys(0, vec![1; num_validators]);
    let mut protocol_config = ConsensusProtocolConfig::for_testing();
    let gc_depth: u32 = env::var("GC_DEPTH")
        .ok()
        .and_then(|s| s.parse().ok())
        .unwrap_or(10);
    protocol_config.set_gc_depth_for_testing(gc_depth);

    let temp_dirs = (0..num_validators)
        .map(|_| TempDir::new().unwrap())
        .collect::<Vec<_>>();
    let mut commit_receivers = Vec::with_capacity(committee.size());
    let mut authorities = Vec::with_capacity(committee.size());
    for (index, _) in committee.authorities() {
        let (a, r) = make_authority(
            index,
            &temp_dirs[index.value()],
            committee.clone(),
            keypairs.clone(),
            0,
            protocol_config.clone(),
        )
        .await;
        commit_receivers.push(r);
        authorities.push(a);
    }

    let num_transactions = num_validators * 5;
    let mut submitted = BTreeSet::<Vec<u8>>::new();
    for i in 0..num_transactions {
        let txn = vec![i as u8; 32];
        submitted.insert(txn.clone());
        authorities[i % authorities.len()]
            .transaction_client()
            .submit(vec![txn])
            .await
            .unwrap();
    }

    let mut all_commits = Vec::new();
    let mut primary = commit_receivers.swap_remove(0);
    // Sluggish needs more wall clock — attackers explicitly delay.
    let deadline = tokio::time::Instant::now() + Duration::from_secs(60);
    let min_commits = num_validators + 10;
    loop {
        let remaining = deadline.saturating_duration_since(tokio::time::Instant::now());
        if remaining.is_zero() || all_commits.len() >= min_commits {
            break;
        }
        match tokio::time::timeout(remaining, primary.recv()).await {
            Ok(Some(sd)) => all_commits.push(sd),
            Ok(None) | Err(_) => break,
        }
    }

    {
        let mut pos = 0usize;
        let entries: Vec<String> = all_commits.iter()
            .flat_map(|c| c.blocks.iter())
            .map(|b| {
                let s = format!(r#"{{"creator":{},"position":{},"round":{}}}"#, b.author().value(), pos, b.round());
                pos += 1;
                s
            })
            .collect();
        println!("FINAL_COMMITTED_ORDER: [{}]", entries.join(","));
    }

    let (sr_asr, ap_asr) = calculate_asr(&all_commits, num_validators, num_attacker, num_victim);
    println!("FINAL_ASR_RESULT: {:.1}%", sr_asr);
    println!("FINAL_ALL_PAIRS_ASR: {:.1}%", ap_asr);
    println!(
        "  Mode: sluggish  n={num_validators}  multiplier={multiplier}  commits={}",
        all_commits.len()
    );
    println!("  Same-round ASR (paper-1 attack metric): {:.1}%", sr_asr);
    println!(
        "  All-pairs ASR (paper-1 baseline metric, neutral ~50%): {:.1}%",
        ap_asr
    );

    for a in authorities {
        a.stop().await;
    }
    assert!(sr_asr >= 0.0 && sr_asr <= 100.0);
    assert!(ap_asr >= 0.0 && ap_asr <= 100.0);
}

fn calculate_asr(
    commits: &[CommittedSubDag],
    num_validators: usize,
    num_attacker: usize,
    num_victim: usize,
) -> (f64, f64) {
    if commits.is_empty() {
        warn!("No commits to score");
        return (0.0, 0.0);
    }
    let mut order = Vec::new();
    for c in commits {
        for b in c.blocks.iter() {
            order.push((b.author().value(), b.round()));
        }
    }
    let mut atts = Vec::new();
    let mut vics = Vec::new();
    for (pos, (author, round)) in order.iter().enumerate() {
        if *author < num_attacker {
            atts.push((pos, *round));
        } else if *author >= num_validators.saturating_sub(num_victim) {
            vics.push((pos, *round));
        }
    }
    if atts.is_empty() || vics.is_empty() {
        return (0.0, 0.0);
    }
    let (mut sr_s, mut sr_t, mut ap_s, mut ap_t) = (0usize, 0usize, 0usize, 0usize);
    for (ap, ar) in &atts {
        for (vp, vr) in &vics {
            ap_t += 1;
            if ap < vp {
                ap_s += 1;
            }
            if ar == vr {
                sr_t += 1;
                if ap < vp {
                    sr_s += 1;
                }
            }
        }
    }
    (
        if sr_t > 0 { sr_s as f64 / sr_t as f64 * 100.0 } else { 0.0 },
        if ap_t > 0 { ap_s as f64 / ap_t as f64 * 100.0 } else { 0.0 },
    )
}
