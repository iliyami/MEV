// Copyright (c) Mysten Labs, Inc.
// SPDX-License-Identifier: Apache-2.0

//! Fissure attack ASR test (paper-1 port to upstream Sui).
//!
//! Reads ATTACK_MODE / ATTACKER_RATIO / VICTIM_RATIO / NUM_NODES from
//! the environment and computes the same-round Attack Success Rate
//! (ASR) for the fissure attack. The attack hooks themselves live in
//! `proposer.rs::ValidatorProposer` and are inert unless ATTACK_MODE
//! is set.

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
                .unwrap_or(2_000),
        ),
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
async fn test_fissure_attack_asr_dynamic() {
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

    let num_attacker = (num_validators as f64 * attacker_ratio).round() as usize;
    let num_victim = (num_validators as f64 * victim_ratio).round() as usize;

    // SAFETY: env vars are set before any ConsensusAuthority is created
    // in this test, so no other thread is reading them concurrently.
    // NO_ATTACK=1 keeps the same scoring scaffold but disables the
    // attacker hook, so the printed ASR is the natural author-index
    // baseline (diagnostic only).
    let no_attack = env::var("NO_ATTACK").ok().filter(|v| v != "0").is_some();
    unsafe {
        if no_attack {
            env::remove_var("ATTACK_MODE");
        } else {
            env::set_var("ATTACK_MODE", "fissure");
        }
        env::set_var("ATTACKER_RATIO", attacker_ratio.to_string());
        env::set_var("VICTIM_RATIO", victim_ratio.to_string());
    }

    info!(
        "Fissure attack ASR test: n={num_validators} attackers={num_attacker} victims={num_victim}"
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
        let (authority, commit_receiver) = make_authority(
            index,
            &temp_dirs[index.value()],
            committee.clone(),
            keypairs.clone(),
            0,
            protocol_config.clone(),
        )
        .await;
        commit_receivers.push(commit_receiver);
        authorities.push(authority);
    }

    let num_transactions: usize = env::var("NUM_TRANSACTIONS")
        .ok()
        .and_then(|s| s.parse().ok())
        .unwrap_or(num_validators * 5);
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

    let collection_secs: u64 = env::var("COLLECTION_DURATION")
        .ok()
        .and_then(|s| s.parse().ok())
        .unwrap_or(35);
    let min_commits: usize = env::var("MIN_COMMITS")
        .ok()
        .and_then(|s| s.parse().ok())
        .unwrap_or(num_validators + 10);

    let mut all_commits = Vec::new();
    let mut primary = commit_receivers.swap_remove(0);
    let deadline = tokio::time::Instant::now() + Duration::from_secs(collection_secs);
    loop {
        let remaining = deadline.saturating_duration_since(tokio::time::Instant::now());
        if remaining.is_zero() || all_commits.len() >= min_commits {
            break;
        }
        match tokio::time::timeout(remaining, primary.recv()).await {
            Ok(Some(sd)) => all_commits.push(sd),
            Ok(None) => {
                warn!("Commit receiver closed");
                break;
            }
            Err(_) => break,
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
        "  Mode: fissure  n={num_validators}  attackers={num_attacker}  victims={num_victim}  commits={}",
        all_commits.len()
    );
    println!(
        "  Same-round ASR (paper-1 attack metric): {:.1}%",
        sr_asr
    );
    println!(
        "  All-pairs ASR (paper-1 baseline metric, neutral ~50%): {:.1}%",
        ap_asr
    );

    for a in authorities {
        a.stop().await;
    }

    assert!(sr_asr >= 0.0 && sr_asr <= 100.0, "same-round ASR out of range: {sr_asr}");
    assert!(ap_asr >= 0.0 && ap_asr <= 100.0, "all-pairs ASR out of range: {ap_asr}");
}

/// Returns (same_round_asr, all_pairs_asr).
/// - same_round_asr: paper-1 attack metric. P(att_pos < vic_pos | same round).
///   Biased high (~89% at n=13) by author-index ordering within a subdag.
/// - all_pairs_asr: paper-1 baseline-style metric. P(att_pos < vic_pos) over
///   ALL pairs, no round filter. Neutral ~50% without an attack.
/// The attack's true signal is the lift of either metric over its
/// no-attack value (paper-1 reports same-round as "attack ASR" and
/// uses all-pairs as the resilience anchor).
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
    let (mut sr_succ, mut sr_total) = (0usize, 0usize);
    let (mut ap_succ, mut ap_total) = (0usize, 0usize);
    for (ap, ar) in &atts {
        for (vp, vr) in &vics {
            ap_total += 1;
            if ap < vp {
                ap_succ += 1;
            }
            if ar == vr {
                sr_total += 1;
                if ap < vp {
                    sr_succ += 1;
                }
            }
        }
    }
    let sr = if sr_total > 0 {
        (sr_succ as f64 / sr_total as f64) * 100.0
    } else {
        0.0
    };
    let ap = if ap_total > 0 {
        (ap_succ as f64 / ap_total as f64) * 100.0
    } else {
        0.0
    };
    (sr, ap)
}
