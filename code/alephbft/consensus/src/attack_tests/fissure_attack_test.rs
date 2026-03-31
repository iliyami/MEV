//! Fissure Attack Test for AlephBFT with 13 Nodes
//!
//! This test measures the Attack Success Rate (ASR) of the fissure attack
//! where attackers exclude victim units from their parent sets.

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
        .or_else(|_| env::var("NUM_NODES"))
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
        .or_else(|_| env::var("DURATION"))
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

fn calculate_pair_baseline_asr(
    finalized_units: &[OrderedUnit<Data, Hasher64>],
    attacker_id: usize,
    victim_id: usize,
) -> f64 {
    if finalized_units.is_empty() {
        log::warn!("No finalized units to calculate ASR");
        return 0.0;
    }
    if attacker_id == victim_id {
        log::warn!("Attacker and victim ids are identical");
        return 0.0;
    }

    let mut attacker_positions = Vec::new();
    let mut victim_positions = Vec::new();
    for (height, unit) in finalized_units.iter().enumerate() {
        let creator = unit.creator.0;
        if creator == attacker_id {
            attacker_positions.push(height);
        } else if creator == victim_id {
            victim_positions.push(height);
        }
    }

    if attacker_positions.is_empty() || victim_positions.is_empty() {
        log::warn!("Missing attacker or victim blocks");
        return 0.0;
    }

    let mut successes = 0usize;
    let mut total_pairs = 0usize;
    for att_pos in &attacker_positions {
        for vic_pos in &victim_positions {
            total_pairs += 1;
            if att_pos < vic_pos {
                successes += 1;
            }
        }
    }

    if total_pairs == 0 {
        log::warn!("No comparable block pairs found");
        return 0.0;
    }

    let asr = (successes as f64 / total_pairs as f64) * 100.0;
    log::info!(
        "📊 Pairwise baseline ASR (node {} vs node {}): {}/{} = {:.2}%",
        attacker_id,
        victim_id,
        successes,
        total_pairs,
        asr
    );
    asr / 100.0
}

#[tokio::test(flavor = "multi_thread")]
async fn test_fissure_attack_asr_13_nodes() {
    init_log();
    
    // Set attack parameters (if not already set by config loader)
    if env::var("ATTACK_MODE").is_err() {
        env::set_var("ATTACK_MODE", "fissure");
    }
    
    // Read configuration from environment variables
    let (num_nodes, num_attackers, num_victims, num_honest, duration_seconds) = get_config();
    
    log::info!("🚀 Starting Fissure Attack Test");
    log::info!("  Network Size: {} nodes", num_nodes);
    log::info!("  Attackers: {} nodes (indices 0-{})", num_attackers, num_attackers - 1);
    log::info!("  Victims: {} nodes (indices {}-{})", num_victims, num_nodes - num_victims, num_nodes - 1);
    log::info!("  Honest: {} nodes (indices {}-{})", num_honest, num_attackers, num_nodes - num_victims - 1);
    log::info!("  Test Duration: {} seconds", duration_seconds);

    let n_members = NodeCount(num_nodes);
    let spawner = Spawner::new();
    
    // Create network hub and get networks for each node
    let (mut net_hub, networks) = Router::new(n_members);
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
    let total_units = finalized_units_guard.len();
    log::info!("📈 Total finalized units collected: {}", total_units);
    
    // Count units by creator
    let mut units_by_creator = std::collections::HashMap::new();
    for unit in finalized_units_guard.iter() {
        *units_by_creator.entry(unit.creator.0).or_insert(0) += 1;
    }
    log::info!("📊 Units by creator: {:?}", units_by_creator);
    
    let asr = calculate_asr_paper_aligned_advanced(&finalized_units_guard, num_nodes, num_attackers, num_victims);
    log::info!("📊 Attack Success Rate (ASR): {:.2}%", asr * 100.0);
    log::info!("Attack Success Rate (ASR): {:.2}%", asr * 100.0);
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

#[tokio::test(flavor = "multi_thread")]
async fn test_baseline_asr_13_nodes_no_attack() {
    init_log();
    
    // Clear attack environment variables to ensure no attack
    env::remove_var("ATTACK_MODE");
    
    // Read configuration from environment variables
    let num_nodes: usize = env::var("NETWORK_SIZE")
        .or_else(|_| env::var("NUM_NODES"))
        .unwrap_or_else(|_| "13".to_string())
        .parse()
        .unwrap_or(13);
    let duration_seconds: u64 = env::var("TEST_DURATION_SECONDS")
        .or_else(|_| env::var("DURATION"))
        .unwrap_or_else(|_| "35".to_string())
        .parse()
        .unwrap_or(35);
    let attacker_id: usize = env::var("ATTACKER_ID")
        .ok()
        .and_then(|s| s.parse().ok())
        .unwrap_or(0)
        .min(num_nodes.saturating_sub(1));
    let victim_id: usize = env::var("VICTIM_ID")
        .ok()
        .and_then(|s| s.parse().ok())
        .unwrap_or(usize::from(num_nodes > 1))
        .min(num_nodes.saturating_sub(1));
    
    log::info!("🚀 Starting Baseline Test (No Attack)");
    log::info!("  Network Size: {} nodes", num_nodes);
    log::info!("  Measured pair: node {} vs node {}", attacker_id, victim_id);
    log::info!("  Expected Baseline ASR: ~50% (random ordering in fair system)");
    log::info!("  Test Duration: {} seconds", duration_seconds);

    let n_members = NodeCount(num_nodes);
    let spawner = Spawner::new();
    
    // Create network hub and get networks for each node
    let (mut net_hub, networks) = Router::new(n_members);
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
    
    // Calculate baseline ASR
    let finalized_units_guard = finalized_units.lock();
    let total_units = finalized_units_guard.len();
    log::info!("📈 Total finalized units collected: {}", total_units);
    
    // Count units by creator
    let mut units_by_creator = std::collections::HashMap::new();
    for unit in finalized_units_guard.iter() {
        *units_by_creator.entry(unit.creator.0).or_insert(0) += 1;
    }
    log::info!("📊 Units by creator: {:?}", units_by_creator);
    
    let asr = calculate_pair_baseline_asr(&finalized_units_guard, attacker_id, victim_id);
    let asr_percent = asr * 100.0;
    log::info!("📊 Baseline Attack Success Rate (ASR): {:.2}%", asr_percent);
    log::info!("📊 FINAL_ASR_RESULT: {:.2}%", asr_percent);
    log::info!("📊 Expected: ~50% (random ordering in fair system)");
    
    drop(finalized_units_guard);
    
    // Cleanup
    for exit_tx in exit_txs {
        let _ = exit_tx.send(());
    }
    for handle in handles {
        let _ = handle.await;
    }
    
    // Validation: Baseline ASR should be around 50% (±15% tolerance)
    // If significantly different, there's measurement bias or protocol issue
    let expected_baseline = 50.0;
    let tolerance = 15.0;
    if (asr_percent - expected_baseline).abs() > tolerance {
        log::warn!("⚠️  Baseline ASR ({:.2}%) deviates significantly from expected ({:.2}% ± {:.2}%)", 
                   asr_percent, expected_baseline, tolerance);
    } else {
        log::info!("✅ Baseline ASR validation: {:.2}% is within expected range ({:.2}% ± {:.2}%)", 
                   asr_percent, expected_baseline, tolerance);
    }
    
    assert!(asr >= 0.0 && asr <= 1.0, "ASR should be between 0 and 1");
}
