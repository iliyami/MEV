// Copyright (c) Mysten Labs, Inc.
// SPDX-License-Identifier: Apache-2.0

//! Mysticeti Leader-Vote Withholding (MLVW) attack ASR test.
//!
//! Mysticeti-specific MEV attack. Each Byzantine attacker excludes the
//! current victim-leader's block from its own R+1 parent set, turning
//! its R+1 block into a blame for that leader. Honest validators are
//! unmodified. Attack hook lives in proposer.rs and is inert unless
//! ATTACK_MODE=mysticeti_lvw.
//!
//! NO_ATTACK=1 disables the hook for the no-attack baseline run while
//! keeping the test scaffold identical.

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
async fn test_mysticeti_lvw_attack_asr_dynamic() {
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

    let no_attack = env::var("NO_ATTACK").ok().filter(|v| v != "0").is_some();
    // ATTACK_MODE_OVERRIDE allows running compound attacks like
    // "mysticeti_lvw_fissure" from the harness without editing the
    // test. Default is "mysticeti_lvw".
    let mode = env::var("ATTACK_MODE_OVERRIDE")
        .unwrap_or_else(|_| "mysticeti_lvw".to_string());
    // SAFETY: env vars are set before any ConsensusAuthority spawns
    // in this test; setup phase is single-threaded.
    unsafe {
        if no_attack {
            env::remove_var("ATTACK_MODE");
        } else {
            env::set_var("ATTACK_MODE", &mode);
        }
        env::set_var("ATTACKER_RATIO", attacker_ratio.to_string());
        env::set_var("VICTIM_RATIO", victim_ratio.to_string());
    }

    info!(
        "MLVW attack ASR test: n={num_validators} attackers={num_attacker} victims={num_victim} no_attack={no_attack}"
    );

    let (committee, keypairs) = local_committee_and_keys(0, vec![1; num_validators]);
    let mut protocol_config = ConsensusProtocolConfig::for_testing();
    let gc_depth: u32 = env::var("GC_DEPTH")
        .ok()
        .and_then(|s| s.parse().ok())
        .unwrap_or(10);
    protocol_config.set_gc_depth_for_testing(gc_depth);
    if let Some(nl) = env::var("NUM_LEADERS_PER_ROUND")
        .ok()
        .and_then(|s| s.parse::<usize>().ok())
    {
        protocol_config.set_num_leaders_per_round_for_testing(Some(nl));
        info!("MLVW test: num_leaders_per_round={nl}");
    }
    if env::var("DISABLE_V3_LEADER_SCORING").ok().filter(|v| v != "0").is_some() {
        protocol_config.set_enable_v3_for_testing(false);
        info!("MLVW test: v3 leader scoring DISABLED");
    }

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
    let collection_secs: u64 = env::var("COLLECTION_DURATION")
        .ok()
        .and_then(|s| s.parse().ok())
        .unwrap_or(45);
    let deadline = tokio::time::Instant::now() + Duration::from_secs(collection_secs);
    let min_commits: usize = env::var("MIN_COMMITS")
        .ok()
        .and_then(|s| s.parse().ok())
        .unwrap_or(num_validators + 10);
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

    // Emit committed order for v2 launcher per-policy ASR computation.
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

    let metrics = calculate_asr(&all_commits, num_validators, num_attacker, num_victim);
    println!("FINAL_ASR_RESULT: {:.1}%", metrics.same_round);
    println!("FINAL_ALL_PAIRS_ASR: {:.1}%", metrics.all_pairs);
    println!("FINAL_NEAR1_ASR: {:.1}%", metrics.near_k1);
    println!("FINAL_NEAR2_ASR: {:.1}%", metrics.near_k2);
    println!(
        "  Mode: mysticeti_lvw  no_attack={no_attack}  n={num_validators}  commits={}",
        all_commits.len()
    );
    println!("  Same-round (K=0): {:.1}%", metrics.same_round);
    println!("  Near-round (K=1): {:.1}%", metrics.near_k1);
    println!("  Near-round (K=2): {:.1}%", metrics.near_k2);
    println!("  All-pairs: {:.1}%", metrics.all_pairs);

    for a in authorities {
        a.stop().await;
    }
    assert!(metrics.same_round >= 0.0 && metrics.same_round <= 100.0);
    assert!(metrics.all_pairs >= 0.0 && metrics.all_pairs <= 100.0);
}

struct AsrMetrics {
    same_round: f64,
    near_k1: f64,
    near_k2: f64,
    all_pairs: f64,
}

fn calculate_asr(
    commits: &[CommittedSubDag],
    num_validators: usize,
    num_attacker: usize,
    num_victim: usize,
) -> AsrMetrics {
    let zero = AsrMetrics {
        same_round: 0.0,
        near_k1: 0.0,
        near_k2: 0.0,
        all_pairs: 0.0,
    };
    if commits.is_empty() {
        warn!("No commits to score");
        return zero;
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
        return zero;
    }
    // K=0 (same-round), K=1 (±1 round), K=2 (±2 rounds), all-pairs
    let (mut sr_s, mut sr_t) = (0usize, 0usize);
    let (mut k1_s, mut k1_t) = (0usize, 0usize);
    let (mut k2_s, mut k2_t) = (0usize, 0usize);
    let (mut ap_s, mut ap_t) = (0usize, 0usize);
    for (apos, ar) in &atts {
        for (vpos, vr) in &vics {
            let rdiff = (*ar as i64 - *vr as i64).unsigned_abs() as u32;
            ap_t += 1;
            if apos < vpos {
                ap_s += 1;
            }
            if rdiff <= 2 {
                k2_t += 1;
                if apos < vpos {
                    k2_s += 1;
                }
            }
            if rdiff <= 1 {
                k1_t += 1;
                if apos < vpos {
                    k1_s += 1;
                }
            }
            if rdiff == 0 {
                sr_t += 1;
                if apos < vpos {
                    sr_s += 1;
                }
            }
        }
    }
    let pct = |s: usize, t: usize| -> f64 {
        if t > 0 { s as f64 / t as f64 * 100.0 } else { 0.0 }
    };
    AsrMetrics {
        same_round: pct(sr_s, sr_t),
        near_k1: pct(k1_s, k1_t),
        near_k2: pct(k2_s, k2_t),
        all_pairs: pct(ap_s, ap_t),
    }
}
