// Copyright (c) Mysten Labs, Inc.
// SPDX-License-Identifier: Apache-2.0

//! Research experiment (not upstream): who wins an equal-fee race for one shared object.
//!
//! Two clients send transactions at the same gas price (the reference gas price), at the
//! same moment, to one shared counter. Client A always submits directly to one chosen
//! validator (the "lane"); client B submits according to `TIE_MODE`. The execution order is
//! read from the effects' Lamport versions (both transactions mutate the counter, so the
//! later one has the strictly higher version). Whether the two landed in the same consensus
//! commit is read from the checkpoint contents (each commit starts with a consensus commit
//! prologue transaction).
//!
//! Only legitimate client choices are exercised: which validator a client submits to.
//! No protocol code is modified by this test.
//!
//! Environment:
//!   TIE_TRIALS   number of races (default 100)
//!   TIE_MODE     "direct"  : B submits directly to the highest-index validator
//!                "reverse" : A uses the highest index, B the lowest (control)
//!                "random"  : B submits directly to a validator chosen uniformly at random
//!                "default" : B uses the full node's normal submission path
//!                "fullnode": A and B each use their own full node; A's is configured with
//!                            `allowed_submission_validators = [lane]`, B's keeps the default
//!                            latency-based choice (the realistic setting)
//!                "fnreverse": as "fullnode", but A's full node is restricted to the highest index
//!   TIE_FEE_MULT both transactions pay this multiple of the reference gas price (default 1)
//!   TIE_NET      "lan" (1-5 ms one-way) or "wan" (25-150 ms one-way)
//!   TIE_FAR_MS   extra one-way delay (ms) added to every link of the lane validator (default 0)
//!   SUI_SEEDED_TIEBREAK "1": the proposed fix (seeded equal-fee tiebreak)
//!   TIE_N        committee size (default 13; set 100 for a mainnet-scale run)
//!   TIE_GEO      "1": spread validators over TIE_REGIONS regions with low intra-region and high
//!                inter-region one-way delay, instead of one uniform latency range
//!   TIE_REGIONS  number of regions when TIE_GEO=1 (default 5)

#[cfg(msim)]
mod test {
    use std::net::SocketAddr;
    use std::sync::Arc;
    use std::time::Duration;

    use rand::Rng;
    use sui_core::authority_client::AuthorityAPI;
    use sui_macros::sim_test;
    use sui_simulator::SimConfig;
    use sui_simulator::configs::uniform_latency_ms;
    use sui_simulator::net::NetSim;
    use sui_simulator::net::config::{InterNodeLatencyMap, LatencyDistribution};
    use sui_simulator::plugin::simulator;
    use sui_swarm_config::genesis_config::{AccountConfig, DEFAULT_GAS_AMOUNT};
    use sui_test_transaction_builder::{
        TestTransactionBuilder, publish_basics_package_and_make_counter,
    };
    use sui_types::base_types::{ObjectRef, SuiAddress};
    use sui_types::digests::TransactionDigest;
    use sui_types::effects::{TransactionEffects, TransactionEffectsAPI};
    use sui_types::messages_grpc::SubmitTxRequest;
    use sui_config::node::TransactionDriverConfig;
    use sui_types::transaction::TransactionDataAPI;
    use sui_types::transaction_driver_types::{ExecuteTransactionRequestType, ExecuteTransactionRequestV3};
    use test_cluster::{TestCluster, TestClusterBuilder};

    fn env(k: &str, d: &str) -> String {
        std::env::var(k).unwrap_or_else(|_| d.to_string())
    }

    fn net_config() -> SimConfig {
        match env("TIE_NET", "lan").as_str() {
            "wan" => uniform_latency_ms(25..150),
            _ => uniform_latency_ms(1..5),
        }
    }

    async fn effects_on_fullnode(cluster: &TestCluster, d: TransactionDigest) -> TransactionEffects {
        cluster
            .fullnode_handle
            .sui_node
            .with(|n| n.state().get_transaction_cache_reader().get_executed_effects(&d))
            .expect("effects must exist after settlement")
    }

    /// Identifies the consensus commit a transaction executed in: the digest of the nearest
    /// preceding consensus commit prologue in the same checkpoint (None if the commit started
    /// in an earlier checkpoint; such trials are left out of the same-commit subset).
    fn commit_of(cluster: &TestCluster, d: TransactionDigest) -> Option<TransactionDigest> {
        cluster.fullnode_handle.sui_node.with(|n| {
            let state = n.state();
            let epoch_store = state.epoch_store_for_testing();
            let ckpt = state
                .get_transaction_checkpoint_for_tests(&d, &epoch_store)
                .ok()??;
            let contents = state.get_checkpoint_contents(ckpt.content_digest).ok()?;
            let reader = state.get_transaction_cache_reader();
            let mut current = None;
            for ed in contents.iter() {
                let tx = reader.get_transaction_block(&ed.transaction)?;
                if tx.transaction_data().is_consensus_commit_prologue() {
                    current = Some(ed.transaction);
                }
                if ed.transaction == d {
                    return current;
                }
            }
            None
        })
    }

    #[sim_test(config = "net_config()")]
    async fn test_equal_fee_race() {
        let trials: usize = env("TIE_TRIALS", "100").parse().unwrap();
        let mode = env("TIE_MODE", "direct");
        let far_ms: u64 = env("TIE_FAR_MS", "0").parse().unwrap();
        let far = far_ms > 0;
        let fix = env("SUI_SEEDED_TIEBREAK", "0") != "0";
        // Committee size (default 13; set TIE_N=100 for a mainnet-scale run) and an optional
        // geographic latency matrix (TIE_GEO=1): validators are spread over TIE_REGIONS regions,
        // with low intra-region and high inter-region one-way delay, instead of one uniform range.
        let n_validators: usize = env("TIE_N", "13").parse().unwrap();
        let geo = env("TIE_GEO", "0") != "0";

        let mut cluster = TestClusterBuilder::new()
            .with_num_validators(n_validators)
            .with_accounts(vec![
                AccountConfig {
                    address: None,
                    gas_amounts: vec![DEFAULT_GAS_AMOUNT; 2],
                };
                2
            ])
            .build()
            .await;

        let (package, counter) = publish_basics_package_and_make_counter(&cluster.wallet).await;
        let fee_mult: u64 = env("TIE_FEE_MULT", "1").parse().unwrap();
        let rgp = cluster.get_reference_gas_price().await * fee_mult;

        // Validators in consensus index order (sorted by protocol key, as in production).
        let committee = cluster.committee();
        let low = *committee.authority_by_index(0).unwrap();
        let high = *committee.authority_by_index((n_validators - 1) as u32).unwrap();
        let (lane, other) = if mode == "reverse" || mode == "fnreverse" { (high, low) } else { (low, high) };

        // Full-node clients: A's full node may only submit to the lane validator; B's full node
        // keeps Sui's default validator choice. Both pay the same extra hop.
        let fn_mode = mode == "fullnode" || mode == "fnreverse";
        let (orch_a, orch_b) = if fn_mode {
            let lane_display = cluster.authority_aggregator().get_display_name(&lane);
            let cfg_a = cluster
                .fullnode_config_builder()
                .with_transaction_driver_config(Some(TransactionDriverConfig {
                    allowed_submission_validators: vec![lane_display],
                    ..Default::default()
                }))
                .build(&mut rand::rngs::OsRng, cluster.swarm.config());
            let fn_a = cluster.start_fullnode_from_config(cfg_a).await;
            let fn_b = cluster.spawn_new_fullnode().await;
            let oa = fn_a.sui_node.with(|n| n.transaction_orchestrator().as_ref().unwrap().clone());
            let ob = fn_b.sui_node.with(|n| n.transaction_orchestrator().as_ref().unwrap().clone());
            (Some(oa), Some(ob))
        } else {
            (None, None)
        };

        if far {
            let lane_node = cluster
                .swarm
                .validator_nodes()
                .find(|v| v.name() == lane)
                .unwrap()
                .get_node_handle()
                .unwrap()
                .with(|n| n.get_sim_node_id());
            let mut ids: Vec<_> = cluster
                .swarm
                .validator_nodes()
                .filter(|v| v.name() != lane)
                .map(|v| v.get_node_handle().unwrap().with(|n| n.get_sim_node_id()))
                .collect();
            ids.push(cluster.fullnode_handle.sui_node.with(|n| n.get_sim_node_id()));
            ids.push(sui_simulator::current_simnode_id());
            let (lo, hi) = match env("TIE_NET", "lan").as_str() {
                "wan" => (25, 150),
                _ => (1, 5),
            };
            let slow = LatencyDistribution::uniform(
                Duration::from_millis(lo + far_ms)..Duration::from_millis(hi + far_ms),
            );
            simulator::<NetSim>().update_config(|cfg| {
                let mut map = InterNodeLatencyMap::new();
                for id in &ids {
                    map = map.with_symmetric_link(lane_node, *id, slow.clone());
                }
                cfg.latency.inter_node_latency = Some(Arc::new(map));
            });
        }

        if geo {
            // Spread validators over regions by consensus index; a low intra-region and a high
            // inter-region one-way delay, in place of the single uniform range. The submitting
            // client and the full node sit in region 0 (a lane user co-located with its chosen
            // validator). This is a deterministic, geography-like latency matrix, not a claim to
            // reproduce any particular topology.
            let regions: usize = env("TIE_REGIONS", "5").parse().unwrap();
            let mut nodes: Vec<(usize, _)> = cluster
                .swarm
                .validator_nodes()
                .map(|v| {
                    let region = committee.authority_index(&v.name()).unwrap() as usize % regions;
                    (region, v.get_node_handle().unwrap().with(|n| n.get_sim_node_id()))
                })
                .collect();
            nodes.push((0, cluster.fullnode_handle.sui_node.with(|n| n.get_sim_node_id())));
            nodes.push((0, sui_simulator::current_simnode_id()));
            let intra = LatencyDistribution::uniform(
                Duration::from_millis(2)..Duration::from_millis(15),
            );
            let inter = LatencyDistribution::uniform(
                Duration::from_millis(50)..Duration::from_millis(150),
            );
            simulator::<NetSim>().update_config(|cfg| {
                let mut map = InterNodeLatencyMap::new();
                for i in 0..nodes.len() {
                    for j in (i + 1)..nodes.len() {
                        let d = if nodes[i].0 == nodes[j].0 { intra.clone() } else { inter.clone() };
                        map = map.with_symmetric_link(nodes[i].1, nodes[j].1, d);
                    }
                }
                cfg.latency.inter_node_latency = Some(Arc::new(map));
            });
        }

        // Two senders, one gas coin each, kept up to date across trials.
        let accounts = cluster.wallet.get_all_accounts_and_gas_objects().await.unwrap();
        let mut senders: Vec<(SuiAddress, ObjectRef)> = accounts
            .iter()
            .filter(|(_, coins)| !coins.is_empty())
            .take(2)
            .map(|(a, coins)| (*a, coins[0]))
            .collect();
        assert_eq!(senders.len(), 2);

        let agg = cluster.authority_aggregator();
        let client_for = |name| agg.authority_clients.get(&name).unwrap().clone();
        let addr = Some(SocketAddr::new([127, 0, 0, 1].into(), 0));

        let (mut a_first, mut same_commit, mut a_first_same, mut lost) = (0, 0, 0, 0);
        for i in 0..trials {
            // Start each race at a random phase of the consensus round.
            let pause = rand::thread_rng().gen_range(50..400);
            tokio::time::sleep(Duration::from_millis(pause)).await;

            let mut signed = Vec::new();
            for (sender, gas) in &senders {
                let tx = TestTransactionBuilder::new(*sender, *gas, rgp)
                    .call_counter_increment(package.0, counter.0, counter.1)
                    .build();
                signed.push(cluster.wallet.sign_transaction(&tx).await);
            }
            let (tx_a, tx_b) = (signed[0].clone(), signed[1].clone());
            let (da, db) = (*tx_a.digest(), *tx_b.digest());

            if fn_mode {
                let (oa, ob) = (orch_a.clone().unwrap(), orch_b.clone().unwrap());
                let ta = tx_a.clone();
                let tb = tx_b.clone();
                let fa = async move {
                    oa.execute_transaction_block(
                        ExecuteTransactionRequestV3::new_v2(ta),
                        ExecuteTransactionRequestType::WaitForEffectsCert,
                        None,
                    )
                    .await
                    .is_ok()
                };
                let fb = async move {
                    ob.execute_transaction_block(
                        ExecuteTransactionRequestV3::new_v2(tb),
                        ExecuteTransactionRequestType::WaitForEffectsCert,
                        None,
                    )
                    .await
                    .is_ok()
                };
                let (ok_a, ok_b) = tokio::join!(fa, fb);
                if !(ok_a && ok_b) {
                    lost += 1;
                    println!("TIE_TRIAL {i} submit_failed");
                    tokio::time::sleep(Duration::from_secs(2)).await;
                    for (_, gas) in senders.iter_mut() {
                        *gas = cluster.wallet.get_object_ref(gas.0).await.unwrap();
                    }
                    continue;
                }
            }
            let lane_client = client_for(lane);
            let fut_a = async move {
                lane_client
                    .authority_client()
                    .submit_transaction(SubmitTxRequest::new_transaction(tx_a), addr)
                    .await
                    .is_ok()
            };
            let names: Vec<_> = committee.names().copied().collect();
            let target_b = if mode == "random" {
                names[rand::thread_rng().gen_range(0..names.len())]
            } else {
                other
            };
            let ok_b = if fn_mode { true } else { match mode.as_str() {
                "default" => {
                    let fut_b = cluster.wallet.execute_transaction_may_fail(tx_b);
                    let (ok_a, rb) = tokio::join!(fut_a, fut_b);
                    ok_a && rb.is_ok()
                }
                _ => {
                    let other_client = client_for(target_b);
                    let fut_b = async move {
                        other_client
                            .authority_client()
                            .submit_transaction(SubmitTxRequest::new_transaction(tx_b), addr)
                            .await
                            .is_ok()
                    };
                    let (ok_a, ok_b) = tokio::join!(fut_a, fut_b);
                    ok_a && ok_b
                }
            } };
            if !ok_b {
                lost += 1;
                println!("TIE_TRIAL {i} submit_failed");
                // Refresh gas refs before continuing.
                tokio::time::sleep(Duration::from_secs(2)).await;
                for (sender, gas) in senders.iter_mut() {
                    *gas = cluster.wallet.get_object_ref(gas.0).await.unwrap();
                    let _ = sender;
                }
                continue;
            }

            cluster.wait_for_tx_settlement(&[da, db]).await;
            let ea = effects_on_fullnode(&cluster, da).await;
            let eb = effects_on_fullnode(&cluster, db).await;
            senders[0].1 = ea.gas_object().unwrap().0;
            senders[1].1 = eb.gas_object().unwrap().0;

            let first_is_a = ea.lamport_version() < eb.lamport_version();
            let ca = commit_of(&cluster, da);
            let cb = commit_of(&cluster, db);
            let same = ca.is_some() && ca == cb;
            a_first += first_is_a as usize;
            same_commit += same as usize;
            a_first_same += (same && first_is_a) as usize;
            println!(
                "TIE_TRIAL {i} a_first={} same_commit={} b_index={} va={} vb={}",
                first_is_a as u8,
                same as u8,
                if fn_mode { 99 } else { committee.authority_index(&target_b).unwrap() },
                ea.lamport_version().value(),
                eb.lamport_version().value()
            );
        }

        let done = trials - lost;
        println!(
            "TIE_SUMMARY mode={mode} n={n_validators} geo={} fee_mult={fee_mult} net={} far_ms={far_ms} far={} fix={} seed={} trials={done} lost={lost} \
             a_first={a_first} same_commit={same_commit} a_first_same_commit={a_first_same} \
             win_all={:.1} win_same_commit={:.1}",
            geo as u8,
            env("TIE_NET", "lan"),
            far as u8,
            fix as u8,
            env("MSIM_TEST_SEED", "?"),
            100.0 * a_first as f64 / done.max(1) as f64,
            100.0 * a_first_same as f64 / same_commit.max(1) as f64,
        );
    }
}
