// Copyright (c) Mysten Labs, Inc.
// SPDX-License-Identifier: Apache-2.0

//! Withholding attack ASR tests for Bullshark (DS4 + DS5).
//!
//! Two legitimate-action "when to broadcast" attacks a rational validator could
//! run without breaking any protocol rule (a withheld proposal is the ordinary
//! slow-link / leader-skip case, which honest nodes already tolerate):
//!   * DS4 — silent-except-leader (bug-free withholding): the attacker proposes
//!     ONLY on its own leader rounds (env `SILENT_EXCEPT_LEADER=1`), so every
//!     block it contributes is an early leader/anchor block.
//!   * DS5 — strategic leader withholding (SLW): the attacker skips ONLY its own
//!     leader-round proposal (`ATTACK_MODE=slw`), the mirror of DS4.
//!
//! The hooks live in `core.rs::try_new_block` and are byte-identical no-ops when
//! neither `SILENT_EXCEPT_LEADER` nor an `slw` `ATTACK_MODE` is set.

use std::{collections::BTreeSet, env, sync::Arc, time::Duration};

use consensus_config::{
    local_committee_and_keys, AuthorityIndex, Committee, NetworkKeyPair, Parameters,
    ProtocolKeyPair,
};
use mysten_metrics::monitored_mpsc::UnboundedReceiver;
use prometheus::Registry;
use sui_protocol_config::{ConsensusNetwork, ProtocolConfig};
use tempfile::TempDir;
use tracing::{info, warn};

use crate::{
    authority_node::ConsensusAuthority,
    block::{BlockAPI, CertifiedBlocksOutput},
    commit::CommittedSubDag,
    mev_attack_metrics::calculate_attack_score,
    transaction::NoopTransactionVerifier,
    Clock, CommitConsumerArgs,
};

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
                .unwrap_or(2_000),
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

/// Shared harness: build an n-validator network, submit a fixed workload,
/// collect commits, emit the campaign markers, and sanity-check the ASR. The
/// caller arms the withholding hook (via env) before invoking this.
async fn run_withholding_asr(label: &str) {
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

    info!(
        "🚀 Withholding attack ASR test [{label}]: n={num_validators} attackers={num_attacker} victims={num_victim}"
    );

    // D2 (skewed stake): env-gated stake vector (comma-separated). Config-only.
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

    for (index, _authority_info) in committee.authorities() {
        let (authority, commit_receiver, _block_receiver) = make_authority(
            index,
            &temp_dirs[index.value()],
            committee.clone(),
            keypairs.clone(),
            ConsensusNetwork::Tonic,
            boot_counters[index],
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

    let mut all_commits = Vec::new();
    let collection_duration_secs: u64 = env::var("COLLECTION_DURATION")
        .ok()
        .and_then(|s| s.parse().ok())
        .unwrap_or(20 + (num_validators as u64) * 2);
    let min_commits: usize = env::var("MIN_COMMITS")
        .ok()
        .and_then(|s| s.parse().ok())
        .unwrap_or(num_validators + 10);
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

    // Committed order (JSON) — lets the launcher compute per-policy / profit-
    // weighted ASR downstream without re-running consensus.
    {
        let mut pos = 0usize;
        let entries: Vec<String> = all_commits
            .iter()
            .flat_map(|c| c.blocks.iter())
            .map(|b| {
                let s = format!(
                    r#"{{"creator":{},"position":{},"round":{}}}"#,
                    b.author().value(),
                    pos,
                    b.round()
                );
                pos += 1;
                s
            })
            .collect();
        println!("FINAL_COMMITTED_ORDER: [{}]", entries.join(","));
    }

    if all_commits.is_empty() {
        warn!("No commits collected for [{label}] — check collection duration / MIN_COMMITS");
    }
    // Same-round ASR is the Low-Index Head Start metric (structurally ~high on a
    // round/author sort, even with no attack). All-pairs ASR is neutral ~50% at
    // baseline, so it — not same-round — reveals a cross-round withholding lift.
    // All-pairs is the headline (parsed as the primary `asr` by the launcher).
    let asr = calculate_attack_score(&all_commits, num_validators, num_attacker, num_victim);
    let ap_asr = calculate_all_pairs_asr(&all_commits, num_validators, num_attacker, num_victim);

    println!("\n========================================");
    println!("🎯 WITHHOLDING ATTACK RESULTS [{label}]:");
    println!("  Mode: {label}");
    println!("  Network: {num_validators} validators");
    println!("  Attackers: {num_attacker}  Victims: {num_victim}");
    println!("  Commits: {}", all_commits.len());
    println!("  Same-round ASR (head start): {asr:.1}%");
    println!("  All-pairs ASR (neutral ~50% baseline): {ap_asr:.1}%");
    println!("  FINAL_ASR_RESULT: {asr:.1}%");
    println!("  FINAL_ALL_PAIRS_ASR: {ap_asr:.1}%");
    println!("========================================\n");

    for authority in authorities {
        authority.stop().await;
    }

    assert!(asr >= 0.0 && asr <= 100.0, "ASR out of range: {asr:.1}%");
    assert!(ap_asr >= 0.0 && ap_asr <= 100.0, "all-pairs ASR out of range: {ap_asr:.1}%");
}

/// All-pairs ASR: over every attacker×victim pair across the whole committed
/// order (not just same-round), the fraction where the attacker is positioned
/// first. Neutral ~50% with no attack — unlike same-round ASR, which is pinned
/// near the low-index head start on a round/author sort.
fn calculate_all_pairs_asr(
    commits: &[CommittedSubDag],
    num_validators: usize,
    num_attacker: usize,
    num_victim: usize,
) -> f64 {
    let mut order: Vec<usize> = Vec::new(); // author at each global position
    for c in commits {
        for b in c.blocks.iter() {
            order.push(b.author().value());
        }
    }
    let mut atts: Vec<usize> = Vec::new();
    let mut vics: Vec<usize> = Vec::new();
    for (position, author) in order.iter().enumerate() {
        if *author < num_attacker {
            atts.push(position);
        } else if *author >= num_validators.saturating_sub(num_victim) {
            vics.push(position);
        }
    }
    if atts.is_empty() || vics.is_empty() {
        return 0.0;
    }
    let (mut s, mut t) = (0usize, 0usize);
    for ap in &atts {
        for vp in &vics {
            t += 1;
            if ap < vp {
                s += 1;
            }
        }
    }
    if t > 0 {
        s as f64 / t as f64 * 100.0
    } else {
        0.0
    }
}

#[tokio::test(flavor = "multi_thread", worker_threads = 4)]
async fn test_withhold_baseline_asr_dynamic() {
    telemetry_subscribers::init_for_testing();

    // Baseline control: the identical harness + metric with NO withholding hook
    // armed, so DS4/DS5 can be reported as a lift over this row.
    let attacker_ratio = env::var("ATTACKER_RATIO").unwrap_or_else(|_| "0.308".to_string());
    let victim_ratio = env::var("VICTIM_RATIO").unwrap_or_else(|_| "0.231".to_string());
    env::remove_var("SILENT_EXCEPT_LEADER");
    env::remove_var("ATTACK_MODE");
    env::set_var("ATTACK_TYPE", "frontrun");
    env::set_var("ATTACKER_RATIO", &attacker_ratio);
    env::set_var("VICTIM_RATIO", &victim_ratio);

    run_withholding_asr("baseline").await;
}

#[tokio::test(flavor = "multi_thread", worker_threads = 4)]
async fn test_withhold_silent_attack_asr_dynamic() {
    telemetry_subscribers::init_for_testing();

    // DS4 isolation: only the silent-except-leader hook is armed. Clear any other
    // attack trigger (hermetic across a combined `cargo test` run), then arm this
    // one; attacker layout is the first `num_attacker` indices (frontrun default).
    let attacker_ratio = env::var("ATTACKER_RATIO").unwrap_or_else(|_| "0.308".to_string());
    let victim_ratio = env::var("VICTIM_RATIO").unwrap_or_else(|_| "0.231".to_string());
    env::remove_var("ATTACK_MODE");
    env::set_var("ATTACK_TYPE", "frontrun");
    env::set_var("ATTACKER_RATIO", &attacker_ratio);
    env::set_var("VICTIM_RATIO", &victim_ratio);
    if env::var("SILENT_EXCEPT_LEADER").is_err() {
        env::set_var("SILENT_EXCEPT_LEADER", "1");
    }

    run_withholding_asr("withhold_silent").await;
}

#[tokio::test(flavor = "multi_thread", worker_threads = 4)]
async fn test_slw_attack_asr_dynamic() {
    telemetry_subscribers::init_for_testing();

    // DS5 isolation: only the SLW leader-round skip is armed. Clear the DS4 env
    // (hermetic across a combined `cargo test` run) before arming slw.
    let attacker_ratio = env::var("ATTACKER_RATIO").unwrap_or_else(|_| "0.308".to_string());
    let victim_ratio = env::var("VICTIM_RATIO").unwrap_or_else(|_| "0.231".to_string());
    env::remove_var("SILENT_EXCEPT_LEADER");
    env::set_var("ATTACK_TYPE", "frontrun");
    env::set_var("ATTACKER_RATIO", &attacker_ratio);
    env::set_var("VICTIM_RATIO", &victim_ratio);
    env::set_var("ATTACK_MODE", "slw");

    run_withholding_asr("slw").await;
}
