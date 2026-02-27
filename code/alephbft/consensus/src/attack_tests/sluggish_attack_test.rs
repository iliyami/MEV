//! Sluggish Attack Test for AlephBFT with 13 Nodes
//!
//! This test measures the Attack Success Rate (ASR) of the sluggish attack
//! where attackers delay unit proposals to manipulate round priority.

use crate::attack_tests::asr_calculation::calculate_asr_paper_aligned_advanced;
use crate::testing::{gen_config, gen_delay_config, init_log};
use crate::{LocalIO, NodeCount, OrderedUnit, UnitFinalizationHandler, run_session, Terminator};
use aleph_bft_mock::{Data, DataProvider, Hasher64, Keychain, Loader, Router, Saver, Spawner};
use aleph_bft_types::SpawnHandle;
use futures::channel::oneshot;
use parking_lot::Mutex;
use std::{env, sync::Arc, time::Duration};

// Helper function to read configuration from environment variables with defaults
fn get_config() -> (usize, usize, usize, usize, u64) {
    let num_nodes = env::var("NETWORK_SIZE")
        .unwrap_or_else(|_| "13".to_string())
        .parse()
        .unwrap_or(13);
    
    let attacker_ratio: f64 = env::var("ATTACKER_RATIO")
        .unwrap_or_else(|_| "0.308".to_string())
        .parse()
        .unwrap_or(0.308);
    
    let victim_ratio: f64 = env::var("VICTIM_RATIO")
        .unwrap_or_else(|_| "0.231".to_string())
        .parse()
        .unwrap_or(0.231);
    
    let num_attackers = (num_nodes as f64 * attacker_ratio).round() as usize;
    let num_victims = (num_nodes as f64 * victim_ratio).round() as usize;
    let num_honest = num_nodes - num_attackers - num_victims;
    
    let duration_seconds: u64 = env::var("TEST_DURATION_SECONDS")
        .unwrap_or_else(|_| "35".to_string())
        .parse()
        .unwrap_or(35);
    
    (num_nodes, num_attackers, num_victims, num_honest, duration_seconds)
}

// Custom handler to collect OrderedUnits for ASR calculation
struct OrderedUnitCollector {
    finalized_units: Arc<Mutex<Vec<OrderedUnit<Data, Hasher64>>>>,
}

impl UnitFinalizationHandler for OrderedUnitCollector {
    type Data = Data;
    type Hasher = Hasher64;

    fn batch_finalized(&mut self, batch: Vec<OrderedUnit<Self::Data, Self::Hasher>>) {
        self.finalized_units.lock().extend(batch);
    }
}

#[tokio::test(flavor = "multi_thread")]
async fn test_sluggish_attack_asr_13_nodes() {
    init_log();
    
    // Set attack parameters (if not already set by config loader)
    if env::var("ATTACK_MODE").is_err() {
        env::set_var("ATTACK_MODE", "sluggish");
    }
    if env::var("SLUGGISH_PROCESSING_DELAY_MS").is_err() {
        env::set_var("SLUGGISH_PROCESSING_DELAY_MS", "11");
    }
    
    // Read configuration from environment variables
    let (num_nodes, num_attackers, num_victims, num_honest, duration_seconds) = get_config();
    
    log::info!("🚀 Starting Sluggish Attack Test");
    log::info!("  Network Size: {} nodes", num_nodes);
    log::info!("  Attackers: {} nodes (indices 0-{})", num_attackers, num_attackers - 1);
    log::info!("  Victims: {} nodes (indices {}-{})", num_victims, num_nodes - num_victims, num_nodes - 1);
    log::info!("  Honest: {} nodes (indices {}-{})", num_honest, num_attackers, num_nodes - num_victims - 1);
    log::info!("  Test Duration: {} seconds", duration_seconds);

    let n_members = NodeCount(num_nodes);
    let spawner = Spawner::new();
    
    // Create network hub and get networks for each node
    let (net_hub, networks) = Router::new(n_members);
    spawner.spawn("network-hub", net_hub);
    
    // Create data providers and spawn members
    // Collect finalized units from node 0 only for consistent ordering
    let mut exit_txs = Vec::new();
    let mut handles = Vec::new();
    let finalized_units = Arc::new(Mutex::new(Vec::<OrderedUnit<Data, Hasher64>>::new()));
    
    for (network, _) in networks {
        let node_id = network.index();
        let data_provider = DataProvider::new();
        
        // Only collect from node 0 for consistent ordering
        let collector = if node_id.0 == 0 {
            OrderedUnitCollector {
                finalized_units: finalized_units.clone(),
            }
        } else {
            // Other nodes use a dummy collector that doesn't collect
            OrderedUnitCollector {
                finalized_units: Arc::new(Mutex::new(Vec::new())),
            }
        };
        
        let config = gen_config(node_id, n_members, gen_delay_config());
        let (exit_tx, exit_rx) = oneshot::channel();
        let unit_loader = Loader::new(vec![]);
        let saved_state = Arc::new(Mutex::new(vec![]));
        let unit_saver: Saver = saved_state.into();
        let local_io = LocalIO::new_with_unit_finalization_handler(
            data_provider,
            collector,
            unit_saver,
            unit_loader,
        );
        
        let network_clone = network;
        let spawner_clone = spawner.clone();
        let member_task = async move {
            let keychain = Keychain::new(n_members, node_id);
            run_session(
                config,
                local_io,
                network_clone,
                keychain,
                spawner_clone,
                Terminator::create_root(exit_rx, "AlephBFT-member"),
            )
            .await
        };
        let handle = spawner.spawn_essential("member", member_task);
        
        exit_txs.push(exit_tx);
        handles.push(handle);
    }
    
    // Wait for consensus to progress
    log::info!("⏳ Waiting for consensus ({} seconds)...", duration_seconds);
    tokio::time::sleep(Duration::from_secs(duration_seconds)).await;
    
    // Calculate ASR
    let finalized_units_guard = finalized_units.lock();
    let asr = calculate_asr_paper_aligned_advanced(&finalized_units_guard, num_nodes, num_attackers, num_victims);
    log::info!("📊 Attack Success Rate (ASR): {:.2}%", asr * 100.0);
    drop(finalized_units_guard);
    
    // Cleanup
    for exit_tx in exit_txs {
        let _ = exit_tx.send(());
    }
    for handle in handles {
        let _ = handle.await;
    }
    
    assert!(asr >= 0.0 && asr <= 1.0, "ASR should be between 0 and 1");
}

