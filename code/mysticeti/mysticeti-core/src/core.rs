// Copyright (c) Mysten Labs, Inc.
// SPDX-License-Identifier: Apache-2.0

use crate::committee::{Authority, Committee};
use crate::crypto::Signer;
use crate::data::Data;
use crate::epoch_close::EpochManager;
use crate::metrics::UtilizationTimerVecExt;
use crate::runtime::timestamp_utc;
use crate::state::CoreRecoveredState;
use crate::threshold_clock::ThresholdClockAggregator;
use crate::types::{
    AuthorityIndex, AuthorityRound, AuthoritySet, BaseStatement, BlockReference, RoundNumber,
    StatementBlock,
};
use crate::wal::{WalPosition, WalSyncer, WalWriter};
use crate::{
    block_handler::BlockHandler, consensus::universal_committer::UniversalCommitterBuilder,
};
use crate::{block_manager::BlockManager, metrics::Metrics};
use rand::Rng;
use crate::{
    block_store::{
        BlockStore, BlockWriter, CommitData, OwnBlockData, WAL_ENTRY_COMMIT, WAL_ENTRY_PAYLOAD,
        WAL_ENTRY_STATE,
    },
    consensus::universal_committer::UniversalCommitter,
};
use crate::{config::Parameters, consensus::linearizer::CommittedSubDag};
use itertools::Itertools;
use minibytes::Bytes;
use std::collections::{HashSet, VecDeque};
use std::env;
use std::mem;
use std::sync::atomic::AtomicU64;
use std::sync::Arc;
use std::time::Instant;

pub struct Core<H: BlockHandler> {
    block_manager: BlockManager,
    pending: VecDeque<(WalPosition, MetaStatement)>,
    last_own_block: OwnBlockData,
    block_handler: H,
    authority: AuthorityIndex,
    threshold_clock: ThresholdClockAggregator,
    committee: Arc<Committee>,
    last_decided_leader: AuthorityRound,
    wal_writer: WalWriter,
    block_store: BlockStore,
    pub(crate) metrics: Arc<Metrics>,
    options: CoreOptions,
    signer: Signer,
    epoch_manager: EpochManager,
    rounds_in_epoch: RoundNumber,
    committer: UniversalCommitter,
    store_retain_rounds: u64,
    wave_length: RoundNumber,
    force_immediate_proposal: bool,
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
        parameters: &Parameters,
        metrics: Arc<Metrics>,
        recovered: CoreRecoveredState,
        mut wal_writer: WalWriter,
        options: CoreOptions,
        signer: Signer,
    ) -> Self {
        let CoreRecoveredState {
            block_store,
            last_own_block,
            mut pending,
            state,
            unprocessed_blocks,
            last_committed_leader,
        } = recovered;
        let mut threshold_clock = ThresholdClockAggregator::new(0, metrics.clone());
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
        let block_manager = BlockManager::new(block_store.clone(), &committee, metrics.clone());

        if let Some(state) = state {
            block_handler.recover_state(&state);
        }

        let epoch_manager = EpochManager::new();

        let committer =
            UniversalCommitterBuilder::new(committee.clone(), block_store.clone(), metrics.clone())
                .with_number_of_leaders(parameters.number_of_leaders)
                .with_pipeline(parameters.enable_pipelining)
                .build();

        let mut this = Self {
            block_manager,
            pending,
            last_own_block,
            block_handler,
            authority,
            threshold_clock,
            committee,
            last_decided_leader: last_committed_leader.unwrap_or_default().into(),
            wal_writer,
            block_store,
            metrics,
            options,
            signer,
            epoch_manager,
            rounds_in_epoch: parameters.rounds_in_epoch(),
            committer,
            store_retain_rounds: parameters.store_retain_rounds,
            wave_length: parameters.wave_length(),
            force_immediate_proposal: false,
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

    // Note that generally when you update this function you also want to change genesis initialization above.
    // The method returns the missing references in order to successfully process the provided blocks. The missing
    // references though will be returned only the first time that a block is provided for processing.
    pub fn add_blocks(&mut self, blocks: Vec<Data<StatementBlock>>) -> Vec<BlockReference> {
        let _timer = self
            .metrics
            .utilization_timer
            .utilization_timer("Core::add_blocks");
        let now = timestamp_utc();
        let (processed, missing_references) = self
            .block_manager
            .add_blocks(blocks, &mut (&mut self.wal_writer, &self.block_store));
        let mut result = Vec::with_capacity(processed.len());
        for (position, processed) in processed
            .into_iter()
            .sorted_by(|b1, b2| b1.1.round().cmp(&b2.1.round()))
        {
            // report latency
            let hostname = self.committee.authority_safe(processed.author()).hostname();
            self.metrics
                .add_block_latency
                .with_label_values(&[&hostname])
                .observe(
                    now.checked_sub(processed.meta_creation_time())
                        .unwrap_or_default()
                        .as_secs_f64(),
                );
            self.threshold_clock
                .add_block(*processed.reference(), &self.committee);
            self.pending
                .push_back((position, MetaStatement::Include(*processed.reference())));
            result.push(processed);
        }

        self.metrics
            .threshold_clock_round
            .set(self.threshold_clock.get_round() as i64);
        
        // CERTIFICATION RACE ATTACK: Aggressive network-layer timing optimization
        if let Ok(attack_mode) = env::var("ATTACK_MODE") {
            if attack_mode == "certification_race" {
                let attacker_ratio: f64 = env::var("ATTACKER_RATIO")
                    .ok()
                    .and_then(|s| s.parse().ok())
                    .unwrap_or(0.33);
                let victim_ratio: f64 = env::var("VICTIM_RATIO")
                    .ok()
                    .and_then(|s| s.parse().ok())
                    .unwrap_or(0.22);
                let committee_size = self.committee.len();
                let attacker_count = ((committee_size as f64) * attacker_ratio).floor() as usize;
                let victim_count = ((committee_size as f64) * victim_ratio).floor() as usize;
                let is_attacker = (self.authority as usize) < attacker_count;
                
                if is_attacker {
                    // AGGRESSIVE STRATEGY 1: Detect victim blocks and trigger immediate proposal
                    let mut victim_block_detected = false;
                    for block in &result {
                        let author_index = block.author() as usize;
                        let is_victim = author_index >= (committee_size - victim_count);
                        if is_victim {
                            victim_block_detected = true;
                            tracing::info!(
                                "🏃 CERTIFICATION RACE: Detected victim block {} from authority {} at round {} - triggering immediate proposal",
                                block.reference(),
                                author_index,
                                block.round()
                            );
                        }
                    }
                    
                    // ULTRA-AGGRESSIVE STRATEGY: Maximize block production for round-level advantages
                    let current_round = self.threshold_clock.get_round();
                    let wave_position = current_round % self.wave_length; // 0=leader, 1=voting ...
                    let is_leader_round = wave_position == 0;
                    let is_decision_round = wave_position == 2;
                    let last_proposed_round = self.last_own_block.block.round();
                    let can_create_new_round = last_proposed_round < current_round;
                    
                    // ULTRA-AGGRESSIVE: Propose at EVERY opportunity for maximum round-level advantage
                    // Strategy: Create blocks at every round to maximize chances of lower-round ordering
                    // This gives us maximum opportunities for round-based ordering advantage
                    let should_race = victim_block_detected || 
                        (can_create_new_round && current_round >= 3); // Propose at EVERY new round we haven't created yet
                    
                    if should_race {
                        self.force_immediate_proposal = true;
                        tracing::info!(
                            "⚡ CERTIFICATION RACE: Attacker {} ULTRA-AGGRESSIVE racing - victim_detected={}, current_round={}, last_proposed={}, wave_pos={} ({}), MAXIMUM_SPEED",
                            self.authority,
                            victim_block_detected,
                            current_round,
                            last_proposed_round,
                            wave_position,
                            if is_leader_round { "LEADER" } else if is_decision_round { "DECISION" } else { "VOTING" }
                        );
                    }
                }
            }
        }
        
        self.run_block_handler(&result);
        missing_references.into_iter().collect()
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
            return None;
        }

        // --- Attack configuration from environment ---
        let attack_mode = env::var("ATTACK_MODE").unwrap_or_default();
        let attacker_ratio: f64 = env::var("ATTACKER_RATIO")
            .ok()
            .and_then(|s| s.parse().ok())
            .unwrap_or(0.33);
        let victim_ratio: f64 = env::var("VICTIM_RATIO")
            .ok()
            .and_then(|s| s.parse().ok())
            .unwrap_or(0.22);
        let committee_size = self.committee.len();
        let attacker_count = ((committee_size as f64) * attacker_ratio).floor() as usize;
        let victim_count = ((committee_size as f64) * victim_ratio).floor() as usize;
        let is_attacker = (attack_mode == "fissure" || attack_mode == "speculative" || attack_mode == "sluggish" || attack_mode == "certification_race")
            && (self.authority as usize) < attacker_count;
        let _is_victim = (self.authority as usize) >= (committee_size - victim_count);

        let default_exclusion: f64 = env::var("EXCLUSION_PROBABILITY")
            .ok()
            .and_then(|s| s.parse().ok())
            .unwrap_or(0.8);
        let _hybrid_exclusion: f64 = env::var("HYBRID_EXCLUSION")
            .ok()
            .and_then(|s| s.parse().ok())
            .unwrap_or(0.05);
        let _speculative_strategy = env::var("SPECULATIVE_STRATEGY").unwrap_or_else(|_| "smart".to_string());
        
        // FISSURE ATTACK (Mysticeti-Specific): Strategic exclusion for wave-based consensus
        // Key insight: Decision rounds (2,5,8...) vote for leaders. Priority = attacker decision blocks > attacker leader > honest > victim
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
        mem::swap(&mut taken, &mut self.pending);
        
        // Collect all includes candidates first
        let mut all_includes = Vec::new();
        all_includes.push(*self.last_own_block.block.reference());
        for (_, statement) in &taken {
            if let MetaStatement::Include(include) = statement {
                all_includes.push(*include);
            }
        }
        
        // REACTIVE FISSURE ATTACK: Same-round frontrunning with maximum exclusion
        // Strategy: Target specific victim blocks for 100% exclusion, maximum exclusion for others
        // Key insight: By excluding victims aggressively, their blocks are delayed/blocked, giving attackers ordering advantage
        let mut includes = if is_attacker && attack_mode == "fissure" {
            let quorum_round = clock_round.saturating_sub(1);
            let quorum_threshold = self.committee.quorum_threshold();
            let own_prev_block = *self.last_own_block.block.reference();
            let mut filtered_includes = vec![own_prev_block];
            
            // STEP 1: Identify target victim blocks for same-round frontrunning
            // WAVE-AWARE TARGETING: Exploit wave structure and boundaries
            let current_wave = clock_round / self.wave_length;
            let wave_position = clock_round % self.wave_length; // 0=leader, 1=voting, 2=decision
            
            tracing::info!(
                "🌊 Wave-Aware Fissure: current_wave={}, wave_pos={} ({}), clock_round={}",
                current_wave,
                wave_position,
                match wave_position { 0 => "LEADER", 1 => "VOTING", 2 => "DECISION", _ => "UNKNOWN" },
                clock_round
            );
            
            // STEP 1: Identify all victim blocks currently in the window
            let mut target_victim_blocks = Vec::new();
            
            // Look at recent rounds in the window to find victim targets
            let min_round = clock_round.saturating_sub(self.wave_length * 2);
            for round in min_round..=clock_round {
                for authority in 0..committee_size {
                    let is_victim = authority >= (committee_size - victim_count);
                    if is_victim {
                        if let Some(block) = self.block_store.get_block_at_authority_round(authority as AuthorityIndex, round) {
                            let block_ref = *block.reference();
                            let victim_wave = round / self.wave_length;
                            let victim_wave_pos = round % self.wave_length;
                            
                            let same_wave = victim_wave == current_wave;
                            let previous_wave_decision = (victim_wave == current_wave.saturating_sub(1)) && (victim_wave_pos == 2);
                            let close_timing = (clock_round as i64 - round as i64).abs() <= 1;
                            let is_decision = victim_wave_pos == 2;
                            let is_leader = victim_wave_pos == 0;
                            let is_critical_round = (is_decision || is_leader) && round >= 3;

                            if same_wave || previous_wave_decision || (close_timing && round >= 3) || is_critical_round {
                                target_victim_blocks.push(block_ref);
                                tracing::info!(
                                    "🎯 WAVE-FRONTRUN TARGET: Victim block {} at round {} wave={} pos={} ({})",
                                    block_ref, round, victim_wave, victim_wave_pos,
                                    match victim_wave_pos { 0 => "LEADER", 1 => "VOTING", 2 => "DECISION", _ => "?" }
                                );
                            }
                        }
                    }
                }
            }
            
            if target_victim_blocks.is_empty() {
                tracing::debug!("🎯 No victim targets identified in window (min_round={})", min_round);
            } else {
                tracing::info!("🎯 Identified {} victim targets for frontrunning", target_victim_blocks.len());
            }

            // STEP 2: Categorize all blocks with safety priority
            let mut attacker_blocks = Vec::new();
            let mut clean_honest_blocks = Vec::new();
            let mut dirty_honest_blocks = Vec::new();
            let mut target_victim_blocks_list = Vec::new(); 
            let mut other_victim_blocks = Vec::new();
            
            // Pass 1: Categorize all available blocks
            let mut current_parent_stake = self.committee.get_stake(self.authority).unwrap_or(0);
            
            for include in &all_includes {
                if *include == own_prev_block { continue; }
                let include_stake = self.committee.get_stake(include.authority).unwrap_or(0);
                let is_victim = (include.authority as usize) >= (committee_size - victim_count);
                let is_attacker = (include.authority as usize) < attacker_count;
                let is_parent = include.round == quorum_round;
                let is_target = target_victim_blocks.contains(include);
                
                if include.round <= 2 {
                    clean_honest_blocks.push((*include, include_stake, is_parent));
                    if is_parent { current_parent_stake += include_stake; }
                    continue;
                }
                
                if is_attacker {
                    attacker_blocks.push((*include, include_stake, is_parent));
                    if is_parent { current_parent_stake += include_stake; }
                } else if !is_victim {
                    let mut includes_target = false;
                    if let Some(block) = self.block_store.get_block(*include) {
                        for parent_ref in block.includes() {
                            if target_victim_blocks.contains(parent_ref) {
                                includes_target = true;
                                break;
                            }
                        }
                    }
                    if includes_target {
                        dirty_honest_blocks.push((*include, include_stake, is_parent));
                    } else {
                        clean_honest_blocks.push((*include, include_stake, is_parent));
                        if is_parent { current_parent_stake += include_stake; }
                    }
                } else if is_target {
                    target_victim_blocks_list.push((*include, include_stake, is_parent));
                } else {
                    other_victim_blocks.push((*include, include_stake, is_parent));
                }
            }

            // Pass 2: Assemble includes starting with clean blocks
            // Add clean honest blocks
            for (include, _, _) in &clean_honest_blocks {
                filtered_includes.push(*include);
            }
            // Add attacker blocks
            for (include, _, _) in &attacker_blocks {
                filtered_includes.push(*include);
            }

            // Pass 3: Fill quorum using dirty/victim blocks ONLY IF NECESSARY
            // Priority: Dirty Honest -> Target Victim -> Other Victim
            if current_parent_stake < quorum_threshold {
                for (include, stake, is_parent) in &dirty_honest_blocks {
                    if current_parent_stake >= quorum_threshold { break; }
                    filtered_includes.push(*include);
                    if *is_parent { current_parent_stake += stake; }
                }
            } else {
                for (include, _, _) in &dirty_honest_blocks {
                    tracing::warn!("🛡️ INDIRECT EXCLUSION: Block {} (Dirty Honest)", include);
                }
            }

            if current_parent_stake < quorum_threshold {
                for (include, stake, is_parent) in &target_victim_blocks_list {
                    if current_parent_stake >= quorum_threshold { break; }
                    filtered_includes.push(*include);
                    if *is_parent { current_parent_stake += stake; }
                }
            } else {
                for (include, _, _) in &target_victim_blocks_list {
                    tracing::warn!("⚔️ EXCLUDING TARGET: Victim block {}", include);
                }
            }
            
            // For remaining other victims, apply stochastic exclusion IF quorum is safe
            for (include, stake, is_parent) in &other_victim_blocks {
                if *is_parent && current_parent_stake < quorum_threshold {
                     filtered_includes.push(*include);
                     current_parent_stake += stake;
                } else if rand::thread_rng().gen_bool(default_exclusion.min(1.0).max(0.0)) {
                     tracing::info!("🎲 STOCHASTIC EXCLUSION: Victim block {}", include);
                } else {
                     filtered_includes.push(*include);
                     if *is_parent { current_parent_stake += stake; }
                }
            }
            
            if !target_victim_blocks_list.is_empty() {
                tracing::info!(
                    "✅ Wave-Fissure attack: Excluded {} target victim blocks (100% exclusion) for wave-aware frontrunning at wave {} pos {}",
                    target_victim_blocks_list.len(),
                    current_wave,
                    wave_position
                );
            }
            
            filtered_includes
        } else {
            all_includes
        };
        
        // Compress the references in the block
        // Iterate through all the include statements in the block, and make a set of all the references in their includes.
        let mut references_in_block: HashSet<BlockReference> = HashSet::new();
        for include in &includes {
            if let Some(block) = self.block_store.get_block(*include) {
                    references_in_block.extend(block.includes());
                }
            }
        
        // Remove redundant includes (already covered by transitive references)
        let own_prev_ref = *self.last_own_block.block.reference();
        
        // CERTIFICATION RACE: Hybrid approach - network timing + selective exclusion
        if let Ok(attack_mode) = env::var("ATTACK_MODE") {
            if attack_mode == "certification_race" {
                let attacker_ratio: f64 = env::var("ATTACKER_RATIO")
                    .ok()
                    .and_then(|s| s.parse().ok())
                    .unwrap_or(0.33);
                let victim_ratio: f64 = env::var("VICTIM_RATIO")
                    .ok()
                    .and_then(|s| s.parse().ok())
                    .unwrap_or(0.22);
                let committee_size = self.committee.len();
                let attacker_count = ((committee_size as f64) * attacker_ratio).floor() as usize;
                let victim_count = ((committee_size as f64) * victim_ratio).floor() as usize;
                let is_attacker = (self.authority as usize) < attacker_count;
                let quorum_round = clock_round.saturating_sub(1);
                
                if is_attacker {
                    // HYBRID STRATEGY: Selective exclusion of victim blocks (not breaking quorum)
                    // Combine network-layer timing with consensus-layer exclusion for maximum ASR
                    let mut filtered_includes: Vec<BlockReference> = vec![own_prev_ref];
                    let mut parent_round_stake = 0u64;
                    let quorum_threshold = self.committee.quorum_threshold();
                    
                    // Use current includes list for certification race filtering
                    let includes_to_process = includes.clone();
                    for include in &includes_to_process {
                        if *include == own_prev_ref {
                            continue;
                        }
                        
                        let include_stake = self.committee.get_stake(include.authority).unwrap_or(0);
                        let is_victim = (include.authority as usize) >= (committee_size - victim_count);
                        let is_attacker_block = (include.authority as usize) < attacker_count;
                        let is_parent = include.round == quorum_round;
                        let is_genesis = include.round <= 2;
                        
                        // Always include genesis and attacker blocks
                        if is_genesis || is_attacker_block {
                            filtered_includes.push(*include);
                            if is_parent {
                                parent_round_stake += include_stake;
                            }
                            continue;
                        }
                        
                        // SELECTIVE EXCLUSION: Exclude victim blocks when safe (maintain quorum)
                        if is_victim && !is_genesis {
                            if is_parent {
                                // For parent blocks: Only exclude if quorum is safe
                                if parent_round_stake >= quorum_threshold {
                                    // 60% exclusion for victim parent blocks (moderate, safe)
                                    let exclusion_prob = 0.60;
                                    let should_exclude = {
                                        let block_digest: &[u8] = include.digest.as_ref();
                                        let mut seed: u64 = 0;
                                        for (i, &byte) in block_digest.iter().take(8).enumerate() {
                                            seed ^= (byte as u64) << (i * 8);
                                        }
                                        seed = seed.wrapping_add(include.round as u64 * 31);
                                        seed = seed.wrapping_add(include.authority as u64 * 17);
                                        (seed % 10000) as f64 / 10000.0 < exclusion_prob
                                    };
                                    
                                    if !should_exclude {
                                        filtered_includes.push(*include);
                                        parent_round_stake += include_stake;
                                    }
                                } else {
                                    // Must include to maintain quorum
                                    filtered_includes.push(*include);
                                    parent_round_stake += include_stake;
                                }
                            } else {
                                // For non-parent blocks: More aggressive exclusion (75%)
                                let exclusion_prob = 0.75;
                                let should_exclude = {
                                    let block_digest: &[u8] = include.digest.as_ref();
                                    let mut seed: u64 = 0;
                                    for (i, &byte) in block_digest.iter().take(8).enumerate() {
                                        seed ^= (byte as u64) << (i * 8);
                                    }
                                    seed = seed.wrapping_add(include.round as u64 * 31);
                                    seed = seed.wrapping_add(include.authority as u64 * 17);
                                    (seed % 10000) as f64 / 10000.0 < exclusion_prob
                                };
                                
                                if !should_exclude {
                                    filtered_includes.push(*include);
                                }
                            }
                        } else {
                            // Include all honest blocks
                            filtered_includes.push(*include);
                            if is_parent {
                                parent_round_stake += include_stake;
                            }
                        }
                    }
                    
                    // Prioritize attacker blocks in final includes list
                    filtered_includes.sort_by(|a, b| {
                        let a_is_attacker = (a.authority as usize) < attacker_count;
                        let b_is_attacker = (b.authority as usize) < attacker_count;
                        let a_is_own = *a == own_prev_ref;
                        let b_is_own = *b == own_prev_ref;
                        
                        match (a_is_own, b_is_own) {
                            (true, false) => std::cmp::Ordering::Less,
                            (false, true) => std::cmp::Ordering::Greater,
                            _ => match (a_is_attacker, b_is_attacker) {
                                (true, false) => std::cmp::Ordering::Less,
                                (false, true) => std::cmp::Ordering::Greater,
                                _ => a.round.cmp(&b.round).then_with(|| a.authority.cmp(&b.authority)),
                            }
                        }
                    });
                    
                    includes = filtered_includes;
                } else {
                    // Non-attacker: Prioritize attacker blocks in includes for ordering advantage
                    includes.sort_by(|a, b| {
                        let a_is_attacker = (a.authority as usize) < attacker_count;
                        let b_is_attacker = (b.authority as usize) < attacker_count;
                        let a_is_own = *a == own_prev_ref;
                        let b_is_own = *b == own_prev_ref;
                        
                        match (a_is_own, b_is_own) {
                            (true, false) => std::cmp::Ordering::Less,
                            (false, true) => std::cmp::Ordering::Greater,
                            _ => match (a_is_attacker, b_is_attacker) {
                                (true, false) => std::cmp::Ordering::Less,
                                (false, true) => std::cmp::Ordering::Greater,
                                _ => a.round.cmp(&b.round).then_with(|| a.authority.cmp(&b.authority)),
                            }
                        }
                    });
                }
            }
        }
        includes.retain(|include| {
            if *include == own_prev_ref {
                true // Always keep own previous block
            } else {
                !references_in_block.contains(include)
            }
        });
        
        // Process statements (payloads)
        for (_, statement) in taken.into_iter() {
            match statement {
                MetaStatement::Include(_) => {
                    // Already processed above
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
        let block = StatementBlock::new_with_signer(
            self.authority,
            clock_round,
            includes,
            statements,
            time_ns,
            self.epoch_changing(),
            self.committee.epoch(),
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
                "Created an oversized block(check all limits set properly!): {:?}",
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

    pub fn leaders(&self, leader_round: RoundNumber) -> Vec<&Authority> {
        let leaders = self.committer.get_leaders(leader_round);

        leaders
            .iter()
            .map(|leader_id| self.committee.authority_safe(*leader_id))
            .collect()
    }

    pub fn wal_syncer(&self) -> WalSyncer {
        self.wal_writer
            .syncer()
            .expect("Failed to create wal syncer")
    }

    pub fn current_round(&self) -> RoundNumber {
        self.threshold_clock.get_round()
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
        let sequence: Vec<_> = self.committer.try_commit(self.last_decided_leader);

        if let Some(last) = sequence.last() {
            self.last_decided_leader = last.clone().into_decided_author_round();
            self.metrics.commit_round.set(last.round() as i64);
        }

        // todo: should ideally come from execution result of epoch smart contract
        if self.last_decided_leader.round() > self.rounds_in_epoch {
            self.epoch_manager.epoch_change_begun();
        }

        sequence
            .into_iter()
            .filter_map(|leader| leader.into_committed_block())
            .collect()
    }

    pub fn cleanup(&self) {
        self.block_store.cleanup(
            self.last_decided_leader
                .round()
                .saturating_sub(self.store_retain_rounds),
        );

        self.block_handler.cleanup();
    }

    /// This only checks readiness in terms of helping liveness for commit rule,
    /// try_new_block might still return None if threshold clock is not ready
    ///
    /// The algorithm to calling is roughly: if timeout || commit_ready_new_block then try_new_block(..)
    pub fn ready_new_block(&self, period: u64, connected_authorities: AuthoritySet) -> bool {
        let quorum_round = self.threshold_clock.get_round();

        // Leader round we check if we have a leader block
        if quorum_round > self.last_decided_leader.round().max(period - 1) {
            let leader_round = quorum_round - 1;
            let leaders = self.committer.get_leaders(leader_round);
            if leaders.is_empty() {
                self.metrics
                    .ready_new_block
                    .with_label_values(&["non_leader_round"])
                    .inc();
                return true;
            }

            let connected_leaders: Vec<_> = leaders
                .iter()
                .filter(|leader| connected_authorities.contains(**leader))
                .cloned()
                .collect();

            if connected_leaders.is_empty() {
                self.metrics
                    .ready_new_block
                    .with_label_values(&["leader_not_connected"])
                    .inc();
                return true;
            }

            if self
                .block_store
                .all_blocks_exists_at_authority_round(&connected_leaders, leader_round)
            {
                // time to receive leader
                let now = Instant::now();
                tracing::debug!(
                    "Leader receive time for round {}: {:?} , {:?}",
                    leader_round,
                    now.duration_since(self.threshold_clock.last_quorum_ts()),
                    leaders
                );

                return true;
            }

            false
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

    pub fn block_store(&self) -> &BlockStore {
        &self.block_store
    }

    pub fn last_own_block(&self) -> &Data<StatementBlock> {
        &self.last_own_block.block
    }

    pub fn last_proposed(&self) -> RoundNumber {
        self.last_own_block.block.round()
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
    
    /// Check if immediate block proposal is requested (for certification race attack)
    pub fn check_and_reset_immediate_proposal(&mut self) -> bool {
        let should_propose = self.force_immediate_proposal;
        self.force_immediate_proposal = false; // Reset after checking
        should_propose
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
    use super::*;
    use crate::test_util::{committee_and_cores, committee_and_cores_persisted};
    use crate::threshold_clock;
    use rand::prelude::StdRng;
    use rand::{Rng, SeedableRng};
    use std::fmt::Write;

    #[test]
    fn test_core_simple_exchange() {
        let (_committee, mut cores, ..) = committee_and_cores(4);

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
            let (committee, mut cores, ..) = committee_and_cores(4);

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
        let (_committee, mut cores, ..) = committee_and_cores_persisted(4, Some(tmp.path()));

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

        let (_committee, mut cores, ..) = committee_and_cores_persisted(4, Some(tmp.path()));

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

        let (_committee, mut cores, ..) = committee_and_cores_persisted(4, Some(tmp.path()));

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
