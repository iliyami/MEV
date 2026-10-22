// Copyright (c) Mysten Labs, Inc.
// SPDX-License-Identifier: Apache-2.0

//! Reactive front-running test (paper-2, answer to review #64A, point A1).
//!
//! Victim transactions stream in over the run, each tagged and submitted to
//! one of the FRONTRUN_VICTIMS highest-indexed validators. The attacker
//! (the FRONTRUN_ATTACKERS lowest-indexed validators) learns a victim
//! transaction only when the victim's block reaches its own DAG; the hook in
//! `proposer.rs::frontrun_prepend` then puts a tagged reaction at the front
//! of its next block. Honest validators run unmodified code.
//!
//! FRONTRUN_MODE=blind is the control: the attacker sees nothing, and the
//! test submits the attacker's transaction to the attacker's own validator
//! at the same instant as the victim's. The front-run success of the two
//! arms separates what seeing the victim buys from what position alone buys.
//!
//! Output: FINAL_TX_ORDER lists every tagged committed transaction in order;
//! FRONTRUN_SUBMIT lists every victim submission with its wall-clock time.

use std::{env, sync::Arc, time::Duration};

use consensus_config::{
    AuthorityIndex, Committee, ConsensusProtocolConfig, NetworkKeyPair, Parameters,
    ProtocolKeyPair, local_committee_and_keys,
};
use mysten_metrics::monitored_mpsc::UnboundedReceiver;
use prometheus::Registry;
use tempfile::TempDir;
use tracing::warn;

use crate::{
    CommitConsumerArgs, Clock,
    authority_node::ConsensusAuthority,
    block::BlockAPI,
    commit::CommittedSubDag,
    proposer::{FRONTRUN_ATTACKER_TAG, FRONTRUN_ID_LEN, FRONTRUN_MEMPOOL, FRONTRUN_VICTIM_TAG},
    transaction::NoopTransactionVerifier,
};

async fn make_authority(
    index: AuthorityIndex,
    db_dir: &TempDir,
    committee: Committee,
    keypairs: Vec<(NetworkKeyPair, ProtocolKeyPair)>,
    protocol_config: ConsensusProtocolConfig,
) -> (ConsensusAuthority, UnboundedReceiver<CommittedSubDag>) {
    let parameters = Parameters {
        db_path: db_dir.path().to_path_buf(),
        dag_state_cached_rounds: 5,
        commit_sync_parallel_fetches: 2,
        commit_sync_batch_size: 3,
        sync_last_known_own_block_timeout: Duration::from_millis(2_000),
        ..Default::default()
    };
    let (commit_consumer, commit_receiver) = CommitConsumerArgs::new(0, 0);
    let authority = ConsensusAuthority::start(
        crate::authority_node::NetworkType::Tonic,
        0,
        committee,
        parameters,
        protocol_config,
        Some(keypairs[index.value()].1.clone()),
        keypairs[index.value()].0.clone(),
        Arc::new(Clock::default()),
        Arc::new(NoopTransactionVerifier {}),
        commit_consumer,
        Registry::new(),
        0,
    )
    .await;
    (authority, commit_receiver)
}

fn env_or<T: std::str::FromStr>(key: &str, default: T) -> T {
    env::var(key).ok().and_then(|s| s.parse().ok()).unwrap_or(default)
}

fn hexs(b: &[u8]) -> String {
    b.iter().map(|x| format!("{:02x}", x)).collect()
}

fn now_ms() -> u128 {
    std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .map(|d| d.as_millis())
        .unwrap_or(0)
}

#[tokio::test(flavor = "multi_thread", worker_threads = 4)]
async fn test_frontrun_reactive() {
    telemetry_subscribers::init_for_testing();

    let n: usize = env_or("NUM_NODES", 13);
    let attackers: usize = env_or("FRONTRUN_ATTACKERS", 1);
    let victims: usize = env_or("FRONTRUN_VICTIMS", 3);
    let interval_ms: u64 = env_or("SUBMIT_INTERVAL_MS", 200);
    let collection_secs: u64 = env_or("COLLECTION_DURATION", 60);
    let seed: u64 = env_or("SEED", 0);
    let blind = env::var("FRONTRUN_MODE").map(|m| m == "blind").unwrap_or(false);
    // FRONTRUN_VISIBILITY=mempool: the attacker also sees each victim
    // transaction while it is pending, FRONTRUN_MEMPOOL_DELAY_MS after it is
    // submitted, as a full-node operator would. Default: blocks only.
    let mempool = env::var("FRONTRUN_VISIBILITY").map(|m| m == "mempool").unwrap_or(false);
    let mempool_delay_ms: u64 = env_or("FRONTRUN_MEMPOOL_DELAY_MS", 50);
    assert!(attackers + victims <= n, "attackers and victims overlap");

    // SAFETY: set before any authority exists, so no other thread reads env.
    unsafe {
        env::set_var("FRONTRUN", "1");
        env::set_var("FRONTRUN_ATTACKERS", attackers.to_string());
        env::set_var("FRONTRUN_VICTIMS", victims.to_string());
    }

    let (committee, keypairs) = local_committee_and_keys(0, vec![1; n]);
    let mut protocol_config = ConsensusProtocolConfig::for_testing();
    protocol_config.set_gc_depth_for_testing(10);

    let temp_dirs = (0..n).map(|_| TempDir::new().unwrap()).collect::<Vec<_>>();
    let mut commit_receivers = Vec::with_capacity(n);
    let mut authorities = Vec::with_capacity(n);
    for (index, _) in committee.authorities() {
        let (authority, rx) = make_authority(
            index,
            &temp_dirs[index.value()],
            committee.clone(),
            keypairs.clone(),
            protocol_config.clone(),
        )
        .await;
        commit_receivers.push(rx);
        authorities.push(authority);
    }

    // Streaming workload. Every tick, one victim transaction goes to the next
    // victim validator in turn and one background transaction to every other
    // validator, so blocks are never empty. The id is (seed, sequence number).
    let clients: Vec<_> = authorities.iter().map(|a| a.transaction_client()).collect();
    let stop_at = tokio::time::Instant::now() + Duration::from_secs(collection_secs.saturating_sub(5));
    let workload = tokio::spawn(async move {
        let mut seq: u32 = 0;
        let mut tick = tokio::time::interval(Duration::from_millis(interval_ms));
        while tokio::time::Instant::now() < stop_at {
            tick.tick().await;
            let v = n - victims + (seq as usize % victims);
            let mut id = Vec::with_capacity(FRONTRUN_ID_LEN);
            id.extend_from_slice(&(seed as u32).to_be_bytes());
            id.extend_from_slice(&seq.to_be_bytes());
            let mut vtx = vec![FRONTRUN_VICTIM_TAG];
            vtx.extend_from_slice(&id);
            vtx.resize(32, 0);
            println!(
                "FRONTRUN_SUBMIT: {{\"victim\":\"{}\",\"vauthor\":{},\"t_ms\":{}}}",
                hexs(&id),
                v,
                now_ms()
            );
            if mempool && !blind {
                if let Ok(mut pool) = FRONTRUN_MEMPOOL.lock() {
                    pool.push((
                        id.clone(),
                        v,
                        std::time::Instant::now() + Duration::from_millis(mempool_delay_ms),
                    ));
                }
            }
            let c = clients[v].clone();
            tokio::spawn(async move {
                let _ = c.submit(vec![vtx]).await;
            });
            if blind {
                // Control arm: same instant, attacker's own validator, no information.
                let mut ftx = vec![FRONTRUN_ATTACKER_TAG];
                ftx.extend_from_slice(&id);
                ftx.push(0);
                ftx.resize(32, 0);
                let c = clients[0].clone();
                tokio::spawn(async move {
                    let _ = c.submit(vec![ftx]).await;
                });
            }
            for (i, c) in clients.iter().enumerate() {
                if i >= n - victims {
                    continue;
                }
                let mut btx = vec![0u8, i as u8];
                btx.extend_from_slice(&seq.to_be_bytes());
                btx.resize(32, 0);
                let c = c.clone();
                tokio::spawn(async move {
                    let _ = c.submit(vec![btx]).await;
                });
            }
            seq = seq.wrapping_add(1);
        }
        seq
    });

    // Collect commits from one validator's view; every validator commits the
    // same sequence, so one view suffices. FRONTRUN_VIEW picks the validator
    // (default 0); timing attacks that block the attacker's own thread lag its
    // view, so those runs read an honest validator's instead.
    let view: usize = env_or("FRONTRUN_VIEW", 0);
    assert!(view < n, "FRONTRUN_VIEW out of range");
    let mut primary = commit_receivers.swap_remove(view);
    let deadline = tokio::time::Instant::now() + Duration::from_secs(collection_secs);
    let mut all_commits = Vec::new();
    loop {
        let remaining = deadline.saturating_duration_since(tokio::time::Instant::now());
        if remaining.is_zero() {
            break;
        }
        match tokio::time::timeout(remaining, primary.recv()).await {
            Ok(Some(sd)) => all_commits.push(sd),
            Ok(None) => {
                warn!("commit receiver closed");
                break;
            }
            Err(_) => break,
        }
    }
    let submitted = workload.await.unwrap_or(0);

    // Measurement-only, transaction-level dump of tagged transactions.
    let mut pos = 0usize;
    let mut entries: Vec<String> = Vec::new();
    for (subdag, c) in all_commits.iter().enumerate() {
        for b in c.blocks.iter() {
            for t in b.transactions() {
                let d = t.data();
                if d.len() > FRONTRUN_ID_LEN
                    && (d[0] == FRONTRUN_VICTIM_TAG || d[0] == FRONTRUN_ATTACKER_TAG)
                {
                    entries.push(format!(
                        r#"{{"tag":"{}","id":"{}","author":{},"round":{},"subdag":{},"pos":{}}}"#,
                        if d[0] == FRONTRUN_VICTIM_TAG { "V" } else { "F" },
                        hexs(&d[1..1 + FRONTRUN_ID_LEN]),
                        b.author().value(),
                        b.round(),
                        subdag,
                        pos
                    ));
                }
                pos += 1;
            }
        }
    }
    println!("FINAL_TX_ORDER: [{}]", entries.join(","));
    println!(
        "FRONTRUN_SUMMARY: n={n} attackers={attackers} victims={victims} blind={blind} mempool={mempool} delay_ms={mempool_delay_ms} attack_mode={} submitted={submitted} commits={}",
        env::var("ATTACK_MODE").unwrap_or_default(),
        all_commits.len()
    );

    for a in authorities {
        a.stop().await;
    }
    assert!(!all_commits.is_empty(), "no commits");
}
