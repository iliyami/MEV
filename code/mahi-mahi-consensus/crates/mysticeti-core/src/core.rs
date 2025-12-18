// Copyright (c) Mysten Labs, Inc.
// SPDX-License-Identifier: Apache-2.0

use std::{
    collections::{HashSet, VecDeque},
    mem,
    sync::{atomic::AtomicU64, Arc},
};
use std::time::Duration;
use rand::Rng;
use tokio::sync::mpsc;
use tokio::sync::mpsc::{Sender, Receiver};
use minibytes::Bytes;

use crate::{
    block_handler::BlockHandler,
    block_manager::BlockManager,
    block_store::{
        BlockStore,
        BlockWriter,
        CommitData,
        OwnBlockData,
        WAL_ENTRY_COMMIT,
        WAL_ENTRY_PAYLOAD,
        WAL_ENTRY_STATE,
    },
    committee::Committee,
    config::{NodePrivateConfig, NodePublicConfig},
    consensus::{
        linearizer::CommittedSubDag,
        universal_committer::{UniversalCommitter, UniversalCommitterBuilder},
    },
    crypto::Signer,
    data::Data,
    epoch_close::EpochManager,
    metrics::{Metrics, UtilizationTimerVecExt},
    runtime::timestamp_utc,
    state::RecoveredState,
    threshold_clock::ThresholdClockAggregator,
    types::{AuthorityIndex, BaseStatement, BlockDigest, BlockReference, RoundNumber, StatementBlock},
    wal::{WalPosition, WalSyncer, WalWriter},
};

pub struct Core<H: BlockHandler> {
    block_manager: BlockManager,
    pending: VecDeque<(WalPosition, MetaStatement)>,
    last_own_block: OwnBlockData,
    block_handler: H,
    authority: AuthorityIndex,
    threshold_clock: ThresholdClockAggregator,
    pub(crate) committee: Arc<Committee>,
    last_commit_leader: BlockReference,
    wal_writer: WalWriter,
    block_store: BlockStore,
    pub(crate) metrics: Arc<Metrics>,
    options: CoreOptions,
    signer: Signer,
    // todo - ugly, probably need to merge syncer and core
    recovered_committed_blocks: Option<(HashSet<BlockReference>, Option<Bytes>)>,
    epoch_manager: EpochManager,
    rounds_in_epoch: RoundNumber,
    committer: UniversalCommitter,
}

pub struct CoreOptions {
    fsync: bool,
}

#[derive(Debug)]
pub enum MetaStatement {
    Include(BlockReference),
    Payload(Vec<BaseStatement>),
}

impl<H: BlockHandler> Core<H> {
    #[allow(clippy::too_many_arguments)]
    pub fn open(
        mut block_handler: H,
        authority: AuthorityIndex,
        committee: Arc<Committee>,
        private_config: NodePrivateConfig,
        public_config: &NodePublicConfig,
        metrics: Arc<Metrics>,
        recovered: RecoveredState,
        mut wal_writer: WalWriter,
        options: CoreOptions,
    ) -> Self {
        let RecoveredState {
            block_store,
            last_own_block,
            mut pending,
            state,
            unprocessed_blocks,
            last_committed_leader,
            committed_blocks,
            committed_state,
        } = recovered;
        let mut threshold_clock = ThresholdClockAggregator::new(0);
        let last_own_block = if let Some(own_block) = last_own_block {
            for (_, pending_block) in pending.iter() {
                if let MetaStatement::Include(include) = pending_block {
                    threshold_clock.add_block(*include, &committee);
                }
            }
            own_block
        } else {
            // todo(fix) - this technically has a race condition if node crashes after genesis
            assert!(pending.is_empty());
            // Initialize empty block store
            // A lot of this code is shared with Self::add_blocks, this is not great and some code reuse would be great
            let (own_genesis_block, other_genesis_blocks) = committee.genesis_blocks(authority);
            assert_eq!(own_genesis_block.author(), authority);
            let mut block_writer = (&mut wal_writer, &block_store);
            for block in other_genesis_blocks {
                let reference = *block.reference();
                threshold_clock.add_block(reference, &committee);
                let position = block_writer.insert_block(block);
                pending.push_back((position, MetaStatement::Include(reference)));
            }
            threshold_clock.add_block(*own_genesis_block.reference(), &committee);
            let own_block_data = OwnBlockData {
                next_entry: WalPosition::MAX,
                block: own_genesis_block,
            };
            block_writer.insert_own_block(&own_block_data);
            own_block_data
        };
        let block_manager = BlockManager::new(block_store.clone(), &committee);

        if let Some(state) = state {
            block_handler.recover_state(&state);
        }

        let epoch_manager = EpochManager::new();

        let committer =
            UniversalCommitterBuilder::new(committee.clone(), block_store.clone(), metrics.clone())
                .with_number_of_leaders(public_config.parameters.number_of_leaders)
                .with_pipeline(public_config.parameters.enable_pipelining)
                .with_wave_length(public_config.parameters.wave_length)
                .build();
        tracing::info!(
            "Pipeline enabled: {}",
            public_config.parameters.enable_pipelining
        );
        tracing::info!(
            "Number of leaders: {}",
            public_config.parameters.number_of_leaders
        );
        tracing::info!(
            "Wave length: {}",
            public_config.parameters.wave_length
        );

        let (tx, mut rx): (Sender<(u128, u128, usize)>, Receiver<(u128, u128, usize)>) = mpsc::channel(10000);

        let mut this = Self {
            block_manager,
            pending,
            last_own_block,
            block_handler,
            authority,
            threshold_clock,
            committee,
            last_commit_leader: last_committed_leader.unwrap_or_default(),
            wal_writer,
            block_store,
            metrics,
            options,
            signer: private_config.keypair,
            recovered_committed_blocks: Some((committed_blocks, committed_state)),
            epoch_manager,
            rounds_in_epoch: public_config.parameters.rounds_in_epoch,
            committer,
        };

        if !unprocessed_blocks.is_empty() {
            tracing::info!(
                "Replaying {} blocks for transaction aggregator",
                unprocessed_blocks.len()
            );
            this.run_block_handler(&unprocessed_blocks);
        }

        this
    }

    pub fn with_options(mut self, options: CoreOptions) -> Self {
        self.options = options;
        self
    }

    // Note that generally when you update this function you also want to change genesis initialization above
    pub fn add_blocks(&mut self, blocks: Vec<Data<StatementBlock>>) -> Vec<Data<StatementBlock>> {
        let _timer = self
            .metrics
            .utilization_timer
            .utilization_timer("Core::add_blocks");
        let processed = self
            .block_manager
            .add_blocks(blocks, &mut (&mut self.wal_writer, &self.block_store));
        let mut result = Vec::with_capacity(processed.len());
        for (position, processed) in processed.into_iter() {
            self.threshold_clock
                .add_block(*processed.reference(), &self.committee);
            self.pending
                .push_back((position, MetaStatement::Include(*processed.reference())));
            result.push(processed);
        }
        self.run_block_handler(&result);
        result
    }

    fn run_block_handler(&mut self, processed: &[Data<StatementBlock>]) {
        let _timer = self
            .metrics
            .utilization_timer
            .utilization_timer("Core::run_block_handler");
        let statements = self
            .block_handler
            .handle_blocks(processed, !self.epoch_changing());
        let serialized_statements =
            bincode::serialize(&statements).expect("Payload serialization failed");
        let position = self
            .wal_writer
            .write(WAL_ENTRY_PAYLOAD, &serialized_statements)
            .expect("Failed to write statements to wal");
        self.pending
            .push_back((position, MetaStatement::Payload(statements)));
    }

    pub fn try_new_block(&mut self) -> Option<Data<StatementBlock>> {
        let _timer = self
            .metrics
            .utilization_timer
            .utilization_timer("Core::try_new_block");
        let clock_round = self.threshold_clock.get_round();
        if clock_round <= self.last_proposed() {
            // tracing::warn!("Did not create block because the TLC round {} is <= last proposed round {}", clock_round, self.last_proposed());
            return None;
        }

        let mut includes = vec![];
        let mut statements = vec![];

        let first_include_index = self
            .pending
            .iter()
            .position(|(_, statement)| match statement {
                MetaStatement::Include(block_ref) => block_ref.round >= clock_round,
                _ => false,
            })
            .unwrap_or(self.pending.len());

        let mut taken = self.pending.split_off(first_include_index);
        // Split off returns the "tail", what we want is keep the tail in "pending" and get the head
        mem::swap(&mut taken, &mut self.pending);
        // Compress the references in the block
        // Iterate through all the include statements in the block, and make a set of all the references in their includes.
        let mut references_in_block: HashSet<BlockReference> = HashSet::new();
        references_in_block.extend(self.last_own_block.block.includes());
        for (_, statement) in &taken {
            if let MetaStatement::Include(block_ref) = statement {
                // for all the includes in the block, add the references in the block to the set
                if let Some(block) = self.block_store.get_block(*block_ref) {
                    references_in_block.extend(block.includes());
                }
            }
        }
        includes.push(*self.last_own_block.block.reference());
        
        // ATTACK IMPLEMENTATION (Fissure & Speculative)
        let attack_mode = std::env::var("ATTACK_MODE").unwrap_or_default();
        let is_attacker = if let Ok(attacker_id) = std::env::var("ATTACKER_ID") {
            self.authority == attacker_id.parse::<AuthorityIndex>().unwrap_or(999)
        } else {
            false
        };
        let victim_id = if let Ok(vid) = std::env::var("VICTIM_ID") {
            vid.parse::<AuthorityIndex>().unwrap_or(999)
        } else {
            999
        };
        let exclusion_prob = std::env::var("EXCLUSION_PROBABILITY")
            .unwrap_or_else(|_| "0.85".to_string())
            .parse::<f64>()
            .unwrap_or(0.85);
        
        // SPECULATIVE ATTACK: Check if using speculative mode
        let speculative_strategy = std::env::var("SPECULATIVE_STRATEGY").unwrap_or_else(|_| "sophisticated".to_string());
        let speculative_p_max = std::env::var("SPECULATIVE_P_MAX")
            .unwrap_or_else(|_| "50".to_string())
            .parse::<usize>()
            .unwrap_or(50);
        
        // Log the attack configuration once
        if attack_mode == "speculative" && is_attacker {
            static LOGGED: std::sync::atomic::AtomicBool = std::sync::atomic::AtomicBool::new(false);
            if !LOGGED.swap(true, std::sync::atomic::Ordering::Relaxed) {
                tracing::info!("🎮 SPECULATIVE ATTACK CONFIG: strategy={}, p_max={}", 
                    speculative_strategy, speculative_p_max);
            }
        }
        
        for (_, statement) in taken.into_iter() {
            match statement {
                MetaStatement::Include(include) => {
                    if !references_in_block.contains(&include) {
                        // Fissure attack: selectively exclude victim blocks
                        if attack_mode == "fissure" && is_attacker && include.authority == victim_id {
                            let mut rng = rand::thread_rng();
                            let random_value: f64 = rng.gen();
                            
                            if random_value < exclusion_prob {
                                // Exclude victim block (Fissure attack)
                                tracing::info!(
                                    "🎯 FISSURE: Attacker {} excluding victim {} block at round {}",
                                    self.authority,
                                    victim_id,
                                    include.round
                                );
                                continue; // Skip adding this victim block
                            } else {
                                tracing::debug!(
                                    "✓ FISSURE: Including victim block ({}% chance)",
                                    (1.0 - exclusion_prob) * 100.0
                                );
                            }
                        }
                        
                        // Speculative attack (Simple strategy): Very light victim exclusion
                        if attack_mode == "speculative" && is_attacker && speculative_strategy == "simple" && include.authority == victim_id {
                            let mut rng = rand::thread_rng();
                            let random_value: f64 = rng.gen();
                            
                            // Use very light exclusion to avoid consensus isolation
                            // Can be overridden by SIMPLE_EXCLUSION_PROB env var
                            let simple_exclusion = std::env::var("SIMPLE_EXCLUSION_PROB")
                                .ok()
                                .and_then(|s| s.parse().ok())
                                .unwrap_or(0.05);  // Default 5% exclusion
                            
                            if random_value < simple_exclusion {
                                tracing::info!(
                                    "🔮 SPECULATIVE (Simple): Attacker {} excluding victim {} block at round {} ({}% exclusion)",
                                    self.authority,
                                    victim_id,
                                    include.round,
                                    simple_exclusion * 100.0
                                );
                                continue;
                            }
                        }
                        
                        includes.push(include);
                    }
                }
                MetaStatement::Payload(payload) => {
                    if !self.epoch_changing() {
                        statements.extend(payload);
                    }
                }
            }
        }

        assert!(!includes.is_empty());
        let time_ns = timestamp_utc().as_nanos();
        
        // HYBRID SLUGGISH ATTACK: Combine timing delays with strategic exclusion
        // Note: Timing delays are applied in syncer.rs, this adds exclusion component
        if attack_mode == "hybrid_sluggish" && is_attacker {
            let exclusion_rate: f64 = std::env::var("HYBRID_EXCLUSION")
                .ok()
                .and_then(|s| s.parse().ok())
                .unwrap_or(0.05); // Default 5% for light hybrid
            
            let own_prev = includes[0];
            let mut rng = rand::thread_rng();
            let mut excluded_count = 0;
            
            // Filter includes with strategic exclusion
            let filtered_includes: Vec<_> = includes.iter().skip(1)
                .filter(|include| {
                    if include.authority == victim_id && rng.gen::<f64>() < exclusion_rate {
                        excluded_count += 1;
                        tracing::debug!(
                            "🐌+🎯 HYBRID_SLUGGISH: Excluded victim block at round {}",
                            include.round
                        );
                        false
                    } else {
                        true
                    }
                })
                .copied()
                .collect();
            
            includes.clear();
            includes.push(own_prev);
            includes.extend(filtered_includes);
            
            tracing::info!(
                "🐌+🎯 HYBRID_SLUGGISH: Excluded {} victim blocks ({}% rate), {} total includes",
                excluded_count, (exclusion_rate * 100.0), includes.len()
            );
        }
        
        // SPECULATIVE ATTACK (RoundRace): Exploit round-based ordering
        // Strategy 1: Prioritize including blocks from lower rounds
        // Strategy 2: Exclude victim blocks from recent rounds
        // Strategy 3: Keep all blocks from older rounds for better ordering
        if attack_mode == "speculative" && is_attacker && speculative_strategy == "roundrace" {
            tracing::info!("🏁 SPECULATIVE (RoundRace): Exploiting round-based ordering");
            
            // Extract own_prev first (always at position 0)
            let own_prev = includes[0];
            let current_round = own_prev.round;
            
            let mut rng = rand::thread_rng();
            
            // Categorize blocks by round and authority
            let mut blocks_by_round: std::collections::BTreeMap<u64, Vec<BlockReference>> = std::collections::BTreeMap::new();
            let mut excluded_count = 0;
            
            for include in includes.iter().skip(1) { // Skip own_prev
                // Strategy: Exclude victim blocks from recent rounds
                // but keep ALL blocks from older rounds (they help us!)
                if include.authority == victim_id && include.round >= current_round.saturating_sub(2) {
                    // 3% chance to exclude recent victim blocks (very conservative)
                    if rng.gen::<f64>() < 0.03 {
                        excluded_count += 1;
                        tracing::debug!(
                            "🏁 ROUNDRACE: Excluded recent victim block from round {}",
                            include.round
                        );
                        continue;
                    }
                }
                
                // Group blocks by round
                blocks_by_round.entry(include.round).or_insert_with(Vec::new).push(*include);
            }
            
            // Rebuild includes with round-optimized ordering
            // Sort each round's blocks to put victim blocks last
            includes.clear();
            includes.push(own_prev); // MUST be first
            
            // Add blocks in round order (lower rounds first = earlier in commit order)
            for (round, mut round_blocks) in blocks_by_round {
                // Within each round, put victim blocks last
                round_blocks.sort_by_key(|b| if b.authority == victim_id { 1 } else { 0 });
                
                let block_count = round_blocks.len();
                includes.extend(round_blocks);
                
                tracing::debug!(
                    "🏁 ROUNDRACE: Added {} blocks from round {}",
                    block_count, round
                );
            }
            
            tracing::info!(
                "🏁 SPECULATIVE (RoundRace): Excluded {} recent victim blocks, {} total blocks",
                excluded_count, includes.len()
            );
        }
        
        // SPECULATIVE ATTACK (Optimal): Conservative strategy with smart exclusion
        // Strategy 1: Conservative exclusion (2-3%) to avoid isolation
        // Strategy 2: Prioritize blocks by round for better ordering  
        // Strategy 3: Smart selection based on multiple factors
        if attack_mode == "speculative" && is_attacker && speculative_strategy == "optimal" {
            tracing::info!("🎯 SPECULATIVE (Optimal): Conservative smart strategy");
            
            // Extract own_prev first (always at position 0)
            let own_prev = includes[0];
            let current_round = own_prev.round;
            
            // Conservative parameters to maintain connectivity
            let mut rng = rand::thread_rng();
            let base_exclusion = 0.02; // Very conservative 2% base
            let max_exclusion = 0.03; // Cap at 3% to avoid isolation
            
            // Categorize blocks
            let mut victim_blocks = Vec::new();
            let mut honest_blocks = Vec::new();
            let mut excluded_count = 0;
            
            for include in includes.iter().skip(1) { // Skip own_prev
                if include.authority == victim_id {
                    // Only exclude victim blocks from older rounds
                    let round_diff = current_round.saturating_sub(include.round);
                    let should_exclude = round_diff > 1 && rng.gen::<f64>() < max_exclusion;
                    
                    if should_exclude {
                        excluded_count += 1;
                        tracing::debug!(
                            "🎯 OPTIMAL: Excluded victim block from round {} (current: {})",
                            include.round, current_round
                        );
                        continue;
                    }
                    victim_blocks.push(*include);
                } else {
                    // Never exclude honest blocks - maintain connectivity
                    honest_blocks.push(*include);
                }
            }
            
            // Sort victim blocks by round (higher rounds first for better positioning)
            victim_blocks.sort_by(|a, b| b.round.cmp(&a.round));
            
            // Sort honest blocks by round (lower rounds first)
            honest_blocks.sort_by(|a, b| a.round.cmp(&b.round));
            
            // Rebuild includes with strategic ordering
            // Order: own_prev -> honest -> victim
            // This puts victim blocks later, potentially helping in LIFO traversal
            includes.clear();
            includes.push(own_prev); // MUST be first
            includes.extend(honest_blocks);
            includes.extend(victim_blocks);
            
            tracing::info!(
                "🎯 SPECULATIVE (Optimal): Excluded {} victim blocks, {} total blocks remaining",
                excluded_count, includes.len()
            );
        }
        
        // SPECULATIVE ATTACK (Smart): Adaptive strategy with round-based manipulation
        // Strategy 1: Adaptive exclusion based on round difference
        // Strategy 2: Strategic block selection to maximize round advantage
        // Strategy 3: Selective connectivity disruption
        if attack_mode == "speculative" && is_attacker && speculative_strategy == "smart" {
            tracing::info!("🧠 SPECULATIVE (Smart): Adaptive round-based strategy");
            
            // Extract own_prev first (always at position 0)
            let own_prev = includes[0];
            let current_round = own_prev.round;
            
            // Adaptive parameters
            let mut rng = rand::thread_rng();
            let base_exclusion = 0.10; // Base 10% exclusion
            let round_penalty = 0.05; // Additional 5% per round behind
            
            // Categorize and filter blocks
            let mut selected_blocks = Vec::new();
            let mut excluded_victim = 0;
            let mut excluded_helper = 0;
            let mut total_victim = 0;
            
            for include in includes.iter().skip(1) { // Skip own_prev
                if include.authority == victim_id {
                    total_victim += 1;
                    // Adaptive exclusion: more aggressive for older rounds
                    let round_diff = current_round.saturating_sub(include.round) as f64;
                    let exclusion_prob = (base_exclusion + round_penalty * round_diff).min(0.5);
                    
                    if rng.gen::<f64>() < exclusion_prob {
                        excluded_victim += 1;
                        tracing::debug!(
                            "🧠 SMART: Excluded victim block (round {}, prob {:.2})",
                            include.round, exclusion_prob
                        );
                        continue;
                    }
                } else {
                    // Also exclude blocks that frequently help victim (helper nodes)
                    // Helper nodes are those that often include victim blocks
                    let is_helper = (include.authority % 3 == victim_id % 3) && include.authority != victim_id;
                    
                    if is_helper && rng.gen::<f64>() < 0.03 { // 3% helper exclusion
                        excluded_helper += 1;
                        tracing::debug!(
                            "🧠 SMART: Excluded helper block from authority {}",
                            include.authority
                        );
                        continue;
                    }
                }
                
                selected_blocks.push(*include);
            }
            
            // Sort blocks by round (lower rounds first) then by authority
            // This ensures blocks from earlier rounds appear earlier in commit order
            selected_blocks.sort_by(|a, b| {
                a.round.cmp(&b.round)
                    .then_with(|| a.authority.cmp(&b.authority))
            });
            
            // Rebuild includes with optimal ordering
            includes.clear();
            includes.push(own_prev); // MUST be first
            includes.extend(selected_blocks);
            
            tracing::info!(
                "🧠 SPECULATIVE (Smart): Excluded {}/{} victim blocks, {} helper blocks, {} total blocks",
                excluded_victim, total_victim, excluded_helper, includes.len()
            );
        }
        
        // SPECULATIVE ATTACK (Hybrid): Combine traversal optimization + light exclusion
        // Strategy 1: Optimize include order for potential DAG traversal advantage
        // Strategy 2: Light victim exclusion (5%) for direct ordering advantage
        if attack_mode == "speculative" && is_attacker && speculative_strategy == "hybrid" {
            tracing::info!("⚡ SPECULATIVE (Hybrid): Traversal optimization + 5% exclusion");
            
            // Extract own_prev first (always at position 0)
            let own_prev = includes[0];
            
            // Part 1: Light victim exclusion + categorize blocks
            let hybrid_exclusion = 0.05; // 5% exclusion
            let mut attacker_includes = Vec::new();
            let mut victim_includes = Vec::new();
            let mut honest_includes = Vec::new();
            let attacker_count = 1; // Single attacker
            
            for include in includes.iter().skip(1) { // Skip own_prev at index 0
                // Check for victim exclusion
                if include.authority == victim_id {
                    let mut rng = rand::thread_rng();
                    let random_value: f64 = rng.gen();
                    if random_value < hybrid_exclusion {
                        tracing::info!(
                            "⚡ SPECULATIVE (Hybrid): Excluding victim block at round {}",
                            include.round
                        );
                        continue; // Skip this victim block
                    }
                    victim_includes.push(*include);
                } else if (include.authority as usize) < attacker_count {
                    attacker_includes.push(*include);
                } else {
                    honest_includes.push(*include);
                }
            }
            
            // Part 2: Rebuild with optimal order for DAG traversal
            // PROTOCOL REQUIREMENT: own_prev must be FIRST (position 0)
            // Strategy: Order remaining blocks to optimize LIFO traversal
            // When leader traverses, blocks from OUR includes are pushed in this order
            // LIFO means: last pushed = first popped = earlier in traversal
            // Order: own_prev (required first) -> victim -> honest
            let attacker_count_for_log = attacker_includes.len();
            includes.clear();
            includes.push(own_prev); // MUST be first (protocol requirement)
            includes.extend(victim_includes);
            includes.extend(honest_includes);
            includes.extend(attacker_includes); // Last for LIFO advantage
            
            tracing::info!(
                "⚡ SPECULATIVE (Hybrid): Applied exclusion + reordering ({} total, {} attacker refs last)",
                includes.len(),
                attacker_count_for_log
            );
        }
        
        // NOVEL TURBO ATTACK: Aggressive round racing with quorum manipulation
        // This is a completely new attack vector that exploits round advancement
        if attack_mode == "speculative" && is_attacker && speculative_strategy == "turbo" {
            tracing::info!("🚀 TURBO ATTACK: Novel round racing strategy");
            
            let own_prev = includes[0];
            let current_round = own_prev.round;
            let target_round = current_round.saturating_sub(1);
            
            // Count blocks per round to understand quorum status
            let mut blocks_by_round: std::collections::BTreeMap<u64, Vec<BlockReference>> = std::collections::BTreeMap::new();
            for include in includes.iter().skip(1) {
                blocks_by_round.entry(include.round).or_insert_with(Vec::new).push(*include);
            }
            
            // Identify quorum blocks (from round-1)
            let quorum_blocks = blocks_by_round.get(&target_round).cloned().unwrap_or_default();
            let quorum_count = quorum_blocks.len();
            
            tracing::debug!("🚀 TURBO: Round {}, found {} blocks from round {}", 
                          current_round, quorum_count, target_round);
            
            // Novel strategy: Include ALL quorum blocks to race rounds
            // Then use LIFO ordering for remaining blocks
            let mut victim_blocks = Vec::new();
            let mut other_blocks = Vec::new();
            
            for (round, blocks) in blocks_by_round.iter() {
                if *round == target_round {
                    continue; // Already handled as quorum blocks
                }
                for block in blocks {
                    if block.authority == victim_id {
                        victim_blocks.push(*block);
                    } else {
                        other_blocks.push(*block);
                    }
                }
            }
            
            // Optimal ordering for turbo attack:
            // 1. Own previous (required)
            // 2. ALL quorum blocks (maximize round advancement)
            // 3. Victim blocks (LIFO disadvantage)
            // 4. Other blocks (LIFO advantage)
            includes.clear();
            includes.push(own_prev);
            includes.extend(quorum_blocks);
            includes.extend(victim_blocks);
            includes.extend(other_blocks);
            
            tracing::info!(
                "🚀 TURBO: Round {}, {} quorum blocks from round {}, {} total includes",
                current_round, quorum_count, target_round, includes.len()
            );
        }
        
        // NOVEL CASCADE ATTACK: Build dependency chains favoring attacker
        // Create block dependencies that favor our blocks in traversal
        if attack_mode == "speculative" && is_attacker && speculative_strategy == "cascade" {
            tracing::info!("🌊 CASCADE ATTACK: Building favorable dependency chains");
            
            let own_prev = includes[0];
            let current_round = own_prev.round;
            
            // Analyze block dependencies - which blocks reference our previous blocks?
            let mut blocks_referencing_us = Vec::new();
            let mut blocks_referencing_victim = Vec::new();
            let mut neutral_blocks = Vec::new();
            let mut victim_blocks = Vec::new();
            
            // Check each block's includes to see who they reference
            for include in includes.iter().skip(1) {
                if include.authority == victim_id {
                    victim_blocks.push(*include);
                } else if let Some(block) = self.block_store.get_block(*include) {
                    let references_attacker = block.includes().iter().any(|r| r.authority == self.authority);
                    let references_victim = block.includes().iter().any(|r| r.authority == victim_id);
                    
                    if references_attacker && !references_victim {
                        // These blocks help build our chain
                        blocks_referencing_us.push(*include);
                    } else if references_victim && !references_attacker {
                        // These blocks help victim's chain
                        blocks_referencing_victim.push(*include);
                    } else {
                        neutral_blocks.push(*include);
                    }
                } else {
                    neutral_blocks.push(*include);
                }
            }
            
            // Strategic ordering to build favorable chains:
            // 1. Own previous (required)
            // 2. Blocks that reference us (strengthen our chain)
            // 3. Neutral blocks
            // 4. Blocks that reference victim (weaken their chain)
            // 5. Victim blocks last
            let ref_us_count = blocks_referencing_us.len();
            let ref_victim_count = blocks_referencing_victim.len();
            
            includes.clear();
            includes.push(own_prev);
            includes.extend(blocks_referencing_us);
            includes.extend(neutral_blocks);
            includes.extend(blocks_referencing_victim);
            includes.extend(victim_blocks);
            
            tracing::info!(
                "🌊 CASCADE: {} blocks reference us, {} reference victim, {} total includes",
                ref_us_count, ref_victim_count, includes.len()
            );
        }
        
        // SPECULATIVE ATTACK (Traversal): Exploit LIFO DAG traversal for same-round ordering
        // Key insight: Linearizer sorts by round only (stable sort), so blocks in same round
        // keep their DAG traversal order. Since traversal is LIFO, blocks added LAST to includes
        // are processed FIRST, appearing EARLIER in final committed order.
        if attack_mode == "speculative" && is_attacker && speculative_strategy == "traversal" {
            tracing::info!("🎯 SPECULATIVE (Traversal): Optimizing include order for DAG traversal");
            
            // Separate includes by type
            let own_prev = includes.remove(0); // Always first
            let mut attacker_includes = Vec::new();
            let mut victim_includes = Vec::new();
            let mut honest_includes = Vec::new();
            
            let committee_size = self.committee.len();
            let attacker_count = if let Ok(ratio_str) = std::env::var("ATTACKER_RATIO") {
                let ratio: f64 = ratio_str.parse().unwrap_or(0.08); // 1/13 default
                ((committee_size as f64) * ratio).floor() as usize
            } else {
                1
            };
            
            for include in includes.iter().skip(0) {
                if (include.authority as usize) < attacker_count {
                    attacker_includes.push(*include);
                } else if include.authority == victim_id {
                    victim_includes.push(*include);
                } else {
                    honest_includes.push(*include);
                }
            }
            
            // Rebuild includes with optimal DAG traversal order:
            // Put attacker blocks LAST so they're processed FIRST (LIFO) and appear EARLIER in commits
            includes.clear();
            includes.push(own_prev);
            
            // Order: own_prev -> victim -> honest -> ATTACKER (last = first in LIFO)
            includes.extend(victim_includes);
            includes.extend(honest_includes);
            includes.extend(attacker_includes); // LAST in includes = FIRST in DAG traversal!
            
            tracing::info!(
                "🎯 SPECULATIVE (Traversal): Reordered {} includes (attacker blocks last for LIFO advantage)",
                includes.len()
            );
        }
        
        // SPECULATIVE ATTACK (Sophisticated): Candidate generation with digest optimization
        // Based on paper: https://eprint.iacr.org/2024/1496.pdf Section 4.2
        if attack_mode == "speculative" && is_attacker && speculative_strategy == "sophisticated" {
            use rand::seq::SliceRandom;
            use rand::thread_rng;
            
            tracing::info!(
                "🔮 SPECULATIVE (Sophisticated): Generating {} candidates for digest optimization",
                speculative_p_max
            );
            
            // Keep track of the best candidate
            let mut best_digest: Option<BlockDigest> = None;
            let mut best_includes = includes.clone();
            
            for attempt in 0..speculative_p_max {
                // Create candidate by shuffling includes (vary ordering)
                // Keep own previous block at position 0 (requirement)
                let mut candidate_includes = includes.clone();
                if candidate_includes.len() > 1 {
                    let own_prev = candidate_includes.remove(0);
                    candidate_includes.shuffle(&mut thread_rng());
                    candidate_includes.insert(0, own_prev);
                }
                
                // Compute candidate digest
                // Note: We're computing a "preview" digest to compare candidates
                // The actual digest will be computed during block creation
                let candidate_digest = crate::crypto::BlockDigest::new(
                    self.authority,
                    clock_round,
                    &candidate_includes,
                    &statements,
                    time_ns,
                    self.epoch_changing(),
                    &crate::crypto::SignatureBytes::default(),
                );
                
                // Select candidate with smallest digest (wins lexicographic ordering)
                if attempt == 0 || candidate_digest < best_digest.unwrap() {
                    best_digest = Some(candidate_digest);
                    best_includes = candidate_includes;
                    
                    if attempt > 0 {
                        tracing::debug!(
                            "🔮 SPECULATIVE: Found better candidate at attempt {} (digest: {:?})",
                            attempt,
                            candidate_digest
                        );
                    }
                }
            }
            
            includes = best_includes;
            tracing::info!(
                "🔮 SPECULATIVE: Selected best of {} candidates (digest: {:?})",
                speculative_p_max,
                best_digest
            );
        }
        let block = StatementBlock::new_with_signer(
            self.authority,
            clock_round,
            includes,
            statements,
            time_ns,
            self.epoch_changing(),
            &self.signer,
        );
        assert_eq!(
            block.includes().get(0).unwrap().authority,
            self.authority,
            "Invalid block {}",
            block
        );

        let block = Data::new(block);
        if block.serialized_bytes().len() > crate::wal::MAX_ENTRY_SIZE / 2 {
            // Sanity check for now
            panic!(
                "Created an oversized block (check all limits set properly: {} > {}): {:?}",
                block.serialized_bytes().len(),
                crate::wal::MAX_ENTRY_SIZE / 2,
                block.detailed()
            );
        }
        self.threshold_clock
            .add_block(*block.reference(), &self.committee);
        self.block_handler.handle_proposal(&block);
        self.proposed_block_stats(&block);
        let next_entry = if let Some((pos, _)) = self.pending.get(0) {
            *pos
        } else {
            WalPosition::MAX
        };
        self.last_own_block = OwnBlockData {
            next_entry,
            block: block.clone(),
        };
        (&mut self.wal_writer, &self.block_store).insert_own_block(&self.last_own_block);

        if self.options.fsync {
            self.wal_writer.sync().expect("Wal sync failed");
        }

        tracing::debug!("Created block {block:?}");

        Some(block)
    }


    pub fn wal_syncer(&self) -> WalSyncer {
        self.wal_writer
            .syncer()
            .expect("Failed to create wal syncer")
    }

    fn proposed_block_stats(&self, block: &Data<StatementBlock>) {
        self.metrics
            .proposed_block_size_bytes
            .observe(block.serialized_bytes().len());
        let mut votes = 0usize;
        let mut transactions = 0usize;
        for statement in block.statements() {
            match statement {
                BaseStatement::Share(_) => transactions += 1,
                BaseStatement::Vote(_, _) => votes += 1,
                BaseStatement::VoteRange(range) => votes += range.len(),
            }
        }
        self.metrics
            .proposed_block_transaction_count
            .observe(transactions);
        self.metrics.proposed_block_vote_count.observe(votes);
    }

    pub fn try_commit(&mut self) -> Vec<Data<StatementBlock>> {
        let sequence: Vec<_> = self
            .committer
            .try_commit(self.last_commit_leader, self.threshold_clock.get_round())
            .into_iter()
            .filter_map(|leader| leader.into_decided_block())
            .collect();

        if let Some(last) = sequence.last() {
            self.last_commit_leader = *last.reference();
        }

        // todo: should ideally come from execution result of epoch smart contract
        if self.last_commit_leader.round() > self.rounds_in_epoch {
            self.epoch_manager.epoch_change_begun();
        }

        sequence
    }

    pub fn cleanup(&self) {
        const RETAIN_BELOW_COMMIT_ROUNDS: RoundNumber = 100;

        self.block_store.cleanup(
            self.last_commit_leader
                .round()
                .saturating_sub(RETAIN_BELOW_COMMIT_ROUNDS),
        );

        self.block_handler.cleanup();
    }

    /// This only checks readiness in terms of helping liveness for commit rule,
    /// try_new_block might still return None if threshold clock is not ready
    ///
    /// The algorithm to calling is roughly: if timeout || commit_ready_new_block then try_new_block(..)
    pub fn ready_new_block(
        &self,
        period: u64,
        connected_authorities: &HashSet<AuthorityIndex>,
    ) -> bool {
        let quorum_round = self.threshold_clock.get_round();

        // Leader round we check if we have a leader block
        if quorum_round > self.last_commit_leader.round().max(period - 1) {
            let leader_round = quorum_round - 1;
            let mut leaders:Vec<_>= self.committee.authorities().map(|i|i).collect() ;// // self.committer.get_leaders(leader_round);
            leaders.retain(|leader| connected_authorities.contains(leader));
            self.block_store
                .all_blocks_exists_at_authority_round(&leaders, leader_round)
        } else {
            false
        }
    }

    pub fn handle_committed_subdag(
        &mut self,
        committed: Vec<CommittedSubDag>,
        state: &Bytes,
    ) -> Vec<CommitData> {
        let mut commit_data = vec![];
        for commit in &committed {
            for block in &commit.blocks {
                self.epoch_manager
                    .observe_committed_block(block, &self.committee);
                tracing::debug!("Committed block: {:?}", block.author_round());
            }
            commit_data.push(CommitData::from(commit));
        }
        self.write_state(); // todo - this can be done less frequently to reduce IO
        self.write_commits(&commit_data, state);
        // todo - We should also persist state of the epoch manager, otherwise if validator
        // restarts during epoch change it will fork on the epoch change state.
        commit_data
    }

    pub fn write_state(&mut self) {
        #[cfg(feature = "simulator")]
        if self.block_handler().state().len() >= crate::wal::MAX_ENTRY_SIZE {
            // todo - this is something needs a proper fix
            // Need to revisit this after we have a proper synchronizer
            // We need to put some limit/backpressure on the accumulator state
            return;
        }
        self.wal_writer
            .write(WAL_ENTRY_STATE, &self.block_handler().state())
            .expect("Write to wal has failed");
    }

    pub fn write_commits(&mut self, commits: &[CommitData], state: &Bytes) {
        let commits = bincode::serialize(&(commits, state)).expect("Commits serialization failed");
        self.wal_writer
            .write(WAL_ENTRY_COMMIT, &commits)
            .expect("Write to wal has failed");
    }

    pub fn take_recovered_committed_blocks(&mut self) -> (HashSet<BlockReference>, Option<Bytes>) {
        self.recovered_committed_blocks
            .take()
            .expect("take_recovered_committed_blocks called twice")
    }

    pub fn block_store(&self) -> &BlockStore {
        &self.block_store
    }

    pub fn last_own_block(&self) -> &Data<StatementBlock> {
        &self.last_own_block.block
    }

    pub fn last_proposed(&self) -> RoundNumber {
        self.last_own_block.block.round()
    }
    
    pub fn threshold_clock(&self) -> &ThresholdClockAggregator {
        &self.threshold_clock
    }

    pub fn authority(&self) -> AuthorityIndex {
        self.authority
    }

    pub fn block_handler(&self) -> &H {
        &self.block_handler
    }

    pub fn block_manager(&self) -> &BlockManager {
        &self.block_manager
    }

    pub fn block_handler_mut(&mut self) -> &mut H {
        &mut self.block_handler
    }

    pub fn committee(&self) -> &Arc<Committee> {
        &self.committee
    }

    pub fn epoch_closed(&self) -> bool {
        self.epoch_manager.closed()
    }

    pub fn epoch_changing(&self) -> bool {
        self.epoch_manager.changing()
    }

    pub fn epoch_closing_time(&self) -> Arc<AtomicU64> {
        self.epoch_manager.closing_time()
    }
}

impl Default for CoreOptions {
    fn default() -> Self {
        Self::test()
    }
}

impl CoreOptions {
    pub fn test() -> Self {
        Self { fsync: false }
    }

    pub fn production() -> Self {
        Self { fsync: true }
    }
}

#[cfg(test)]
mod test {
    use std::fmt::Write;

    use rand::{prelude::StdRng, Rng, SeedableRng};

    use super::*;
    use crate::{
        test_util::{committee_and_cores, committee_and_cores_persisted},
        threshold_clock,
    };

    #[test]
    fn test_core_simple_exchange() {
        let (_committee, mut cores, _) = committee_and_cores(4);

        let mut proposed_transactions = vec![];
        let mut blocks = vec![];
        for core in &mut cores {
            core.run_block_handler(&[]);
            let block = core
                .try_new_block()
                .expect("Must be able to create block after genesis");
            assert_eq!(block.reference().round, 1);
            proposed_transactions.extend(core.block_handler.proposed.drain(..));
            eprintln!("{}: {}", core.authority, block);
            blocks.push(block.clone());
        }
        assert_eq!(proposed_transactions.len(), 4);
        let more_blocks = blocks.split_off(1);

        eprintln!("===");

        let mut blocks_r2 = vec![];
        for core in &mut cores {
            core.add_blocks(blocks.clone());
            assert!(core.try_new_block().is_none());
            core.add_blocks(more_blocks.clone());
            let block = core
                .try_new_block()
                .expect("Must be able to create block after full round");
            eprintln!("{}: {}", core.authority, block);
            assert_eq!(block.reference().round, 2);
            blocks_r2.push(block.clone());
        }

        for core in &mut cores {
            core.add_blocks(blocks_r2.clone());
            let block = core
                .try_new_block()
                .expect("Must be able to create block after full round");
            eprintln!("{}: {}", core.authority, block);
            assert_eq!(block.reference().round, 3);
            for txid in &proposed_transactions {
                assert!(
                    core.block_handler.is_certified(txid),
                    "Transaction {} is not certified by {}",
                    txid,
                    core.authority
                );
            }
        }
    }

    #[test]
    fn test_randomized_simple_exchange() {
        'l: for seed in 0..100 {
            let mut rng = StdRng::from_seed([seed; 32]);
            let (committee, mut cores, _) = committee_and_cores(4);

            let mut proposed_transactions = vec![];
            let mut pending: Vec<_> = committee.authorities().map(|_| vec![]).collect();
            for core in &mut cores {
                core.run_block_handler(&[]);
                let block = core
                    .try_new_block()
                    .expect("Must be able to create block after genesis");
                assert_eq!(block.reference().round, 1);
                proposed_transactions.extend(core.block_handler.proposed.drain(..));
                eprintln!("{}: {}", core.authority, block);
                assert!(
                    threshold_clock::threshold_clock_valid_non_genesis(&block, &committee),
                    "Invalid clock {}",
                    block
                );
                push_all(&mut pending, core.authority, &block);
            }
            // Each iteration we pick one authority and deliver to it 1..3 random blocks
            // First 20 iterations we record all transactions created by authorities
            // After this we wait for those recorded transactions to be eventually certified
            'a: for i in 0..1000 {
                let authority = committee.random_authority(&mut rng);
                eprintln!("Iteration {i}, authority {authority}");
                let core = &mut cores[authority as usize];
                let this_pending = &mut pending[authority as usize];
                let c = rng.gen_range(1..4usize);
                let mut blocks = vec![];
                let mut deliver = String::new();
                for _ in 0..c {
                    if this_pending.is_empty() {
                        break;
                    }
                    let block = this_pending.remove(rng.gen_range(0..this_pending.len()));
                    write!(deliver, "{}, ", block).ok();
                    blocks.push(block);
                }
                if blocks.is_empty() {
                    eprintln!("No pending blocks for {authority}");
                    continue;
                }
                eprint!("Deliver {deliver} to {authority} => ");
                core.add_blocks(blocks);
                let Some(block) = core.try_new_block() else {
                    eprintln!("No new block");
                    continue;
                };
                assert!(
                    threshold_clock::threshold_clock_valid_non_genesis(&block, &committee),
                    "Invalid clock {}",
                    block
                );
                eprintln!("Created {block}");
                push_all(&mut pending, core.authority, &block);
                if i < 20 {
                    // First 20 iterations we record proposed transactions
                    proposed_transactions.extend(core.block_handler.proposed.drain(..));
                    // proposed_transactions.push(core.block_handler.last_transaction());
                } else {
                    assert!(!proposed_transactions.is_empty());
                    // After 20 iterations we just wait for all transactions to be committed everywhere
                    for proposed in &proposed_transactions {
                        for core in &cores {
                            if !core.block_handler.is_certified(proposed) {
                                continue 'a;
                            }
                        }
                    }
                    println!(
                        "Seed {seed} succeed, {} transactions certified in {i} exchanges",
                        proposed_transactions.len()
                    );
                    continue 'l;
                }
            }
            panic!("Seed {seed} failed - not all transactions are committed");
        }
    }

    #[test]
    fn test_core_recovery() {
        let tmp = tempdir::TempDir::new("test_core_recovery").unwrap();
        let (_committee, mut cores, _) = committee_and_cores_persisted(4, Some(tmp.path()));

        let mut proposed_transactions = vec![];
        let mut blocks = vec![];
        for core in &mut cores {
            core.run_block_handler(&[]);
            let block = core
                .try_new_block()
                .expect("Must be able to create block after genesis");
            assert_eq!(block.reference().round, 1);
            proposed_transactions.extend(core.block_handler.proposed.clone());
            eprintln!("{}: {}", core.authority, block);
            blocks.push(block.clone());
        }
        assert_eq!(proposed_transactions.len(), 4);
        cores.iter_mut().for_each(Core::write_state);
        drop(cores);

        let (_committee, mut cores, _) = committee_and_cores_persisted(4, Some(tmp.path()));

        let more_blocks = blocks.split_off(2);

        eprintln!("===");

        let mut blocks_r2 = vec![];
        for core in &mut cores {
            core.add_blocks(blocks.clone());
            assert!(core.try_new_block().is_none());
            core.add_blocks(more_blocks.clone());
            let block = core
                .try_new_block()
                .expect("Must be able to create block after full round");
            eprintln!("{}: {}", core.authority, block);
            assert_eq!(block.reference().round, 2);
            blocks_r2.push(block.clone());
        }

        // Note that we do not call Core::write_state here unlike before.
        // This should also be handled correctly by re-processing unprocessed_blocks
        drop(cores);

        eprintln!("===");

        let (_committee, mut cores, _) = committee_and_cores_persisted(4, Some(tmp.path()));

        for core in &mut cores {
            core.add_blocks(blocks_r2.clone());
            let block = core
                .try_new_block()
                .expect("Must be able to create block after full round");
            eprintln!("{}: {}", core.authority, block);
            assert_eq!(block.reference().round, 3);
            for txid in &proposed_transactions {
                assert!(
                    core.block_handler.is_certified(txid),
                    "Transaction {} is not certified by {}",
                    txid,
                    core.authority
                );
            }
        }
    }

    fn push_all(
        p: &mut Vec<Vec<Data<StatementBlock>>>,
        except: AuthorityIndex,
        block: &Data<StatementBlock>,
    ) {
        for (i, q) in p.iter_mut().enumerate() {
            if i as AuthorityIndex != except {
                q.push(block.clone());
            }
        }
    }
}
