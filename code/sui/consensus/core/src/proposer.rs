// Copyright (c) Mysten Labs, Inc.
// SPDX-License-Identifier: Apache-2.0

use std::{collections::BTreeSet, env, iter, sync::Arc, time::Duration};

use consensus_config::ProtocolKeyPair;
use consensus_types::block::{BlockRef, BlockTimestampMs, Round};
use parking_lot::RwLock;
use tokio::time::Instant;
use tracing::{debug, info, trace};

use crate::{
    ancestor::{AncestorState, AncestorStateManager},
    block::{
        Block, BlockAPI, BlockV1, BlockV2, ExtendedBlock, GENESIS_ROUND, SignedBlock, Slot,
        VerifiedBlock,
    },
    context::Context,
    dag_state::DagState,
    leader_schedule_v3::NextCommitLeaderSchedule,
    round_tracker::RoundTracker,
    stake_aggregator::{QuorumThreshold, StakeAggregator},
    transaction::TransactionConsumer,
    transaction_vote_tracker::TransactionVoteTracker,
    universal_committer::UniversalCommitter,
};

const MAX_COMMIT_VOTES_PER_BLOCK: usize = 100;

/// Trait for handling block proposal logic.
/// Only Validators have a proposer; Observers use None for the proposer field in Core.
pub(crate) trait Proposer: Send + Sync {
    /// Attempts to create and return a new block proposal.
    /// Returns None if conditions for proposal are not met.
    fn try_new_block(&mut self, force: bool) -> Option<ExtendedBlock>;

    /// Returns whether this node should propose blocks
    fn should_propose(&self) -> bool;

    /// Sets the propagation delay (validators only)
    fn set_propagation_delay(&mut self, delay: Round);

    /// Sets the last known proposed round (validators only)
    fn set_last_known_proposed_round(&mut self, round: Round);

    /// Gets the last known proposed round if applicable
    fn get_last_known_proposed_round(&self) -> Option<Round>;

    /// Returns the round of the last proposed block (validators only)
    fn last_proposed_round(&self) -> Round;

    /// Returns the last proposed block (validators only)
    fn last_proposed_block(&self) -> VerifiedBlock;

    /// Sets propagation scores on the ancestor state manager (validators only)
    fn set_propagation_scores(&mut self, scores: crate::leader_scoring::ReputationScores);

    /// Sets the next v3 commit leader schedule used to wait before proposing.
    #[allow(dead_code)]
    fn set_next_commit_leader_schedule(&mut self, schedule: NextCommitLeaderSchedule);

    /// Notifies transaction consumer about committed own blocks (validators only)
    fn notify_own_blocks_committed(&self, block_refs: Vec<BlockRef>, gc_round: Round);

    /// Returns the round tracker for tests (validators only)
    #[cfg(test)]
    fn round_tracker_for_tests(&self) -> Arc<RwLock<RoundTracker>>;
}

/// Validator proposal engine - full block proposal implementation
pub(crate) struct ValidatorProposer {
    context: Arc<Context>,
    transaction_consumer: TransactionConsumer,
    transaction_vote_tracker: TransactionVoteTracker,
    propagation_delay: Round,
    last_included_ancestors: Vec<Option<BlockRef>>,
    block_signer: ProtocolKeyPair,
    last_known_proposed_round: Option<Round>,
    ancestor_state_manager: AncestorStateManager,
    round_tracker: Arc<RwLock<RoundTracker>>,
    dag_state: Arc<RwLock<DagState>>,
    leader_waiter: ProposalLeaderWaiter,

    // Paper-1 MEV attack configuration, read once at construction from
    // environment variables. When ATTACK_MODE is unset the hooks below
    // are inert and the proposal path is byte-identical to upstream Sui.
    attack_mode: String,
    attack_type: String,
    is_attacker: bool,
    attack_active: bool,
    speculative_p_max: usize,
    sluggish_timeout_multiplier: f64,

    // Paper-2 v2 coordinator integration. When V2_COORDINATOR_URL is set,
    // per-node policy comes from the coordinator instead of global env vars.
    coordinator_url: Option<String>,
    profit_threshold: Option<f64>,
    role_action: Option<String>,
    own_group_id: Option<String>,
}

impl ValidatorProposer {
    pub(crate) fn new(
        dag_state: Arc<RwLock<DagState>>,
        context: Arc<Context>,
        transaction_consumer: TransactionConsumer,
        transaction_vote_tracker: TransactionVoteTracker,
        block_signer: ProtocolKeyPair,
        last_known_proposed_round: Option<Round>,
        ancestor_state_manager: AncestorStateManager,
        round_tracker: Arc<RwLock<RoundTracker>>,
        leader_waiter: ProposalLeaderWaiter,
    ) -> Self {
        let last_included_ancestors = vec![None; context.committee.size()];

        // Read attack config from environment. SPECULATIVE_P_MAX and
        // SLUGGISH_TIMEOUT_MULTIPLIER are required only when the
        // corresponding ATTACK_MODE is requested.
        let mut attack_mode = env::var("ATTACK_MODE").unwrap_or_default();
        let mut attack_type = env::var("ATTACK_TYPE").unwrap_or_else(|_| "frontrun".to_string());
        let attacker_ratio: f64 = env::var("ATTACKER_RATIO")
            .ok()
            .and_then(|s| s.parse().ok())
            .unwrap_or(0.33);
        let mut speculative_p_max: usize = env::var("SPECULATIVE_P_MAX")
            .ok()
            .and_then(|s| s.parse().ok())
            .unwrap_or_else(|| {
                if attack_mode == "speculative" {
                    panic!(
                        "SPECULATIVE_P_MAX must be set when ATTACK_MODE=speculative"
                    );
                }
                50
            });
        let mut sluggish_timeout_multiplier: f64 = env::var("SLUGGISH_TIMEOUT_MULTIPLIER")
            .ok()
            .and_then(|s| s.parse().ok())
            .unwrap_or_else(|| {
                if attack_mode == "sluggish" {
                    panic!(
                        "SLUGGISH_TIMEOUT_MULTIPLIER must be set when ATTACK_MODE=sluggish"
                    );
                }
                2.0
            });
        let mut attack_active = matches!(
            attack_mode.as_str(),
            "fissure" | "speculative" | "sluggish" | "mysticeti_lvw" | "mysticeti_lvw_fissure" | "mysticeti_eclipse" | "mysticeti_eclipse_lvw" | "mysticeti_withhold" | "mysticeti_withhold_lvw" | "mysticeti_slw" | "mysticeti_slw_fissure"
        );
        // Eclipse modes also activate MLVW
        let mlvw_active_for_init = attack_mode.contains("lvw") || attack_mode.contains("eclipse");
        let committee_size = context.committee.size();
        let attacker_count = ((committee_size as f64) * attacker_ratio).floor() as usize;
        let mut is_attacker = attack_active && context.own_index.value() < attacker_count;

        // v2 coordinator override: when V2_COORDINATOR_URL is set, per-node
        // policy comes from the HTTP coordinator instead of global env vars.
        let coordinator_url = env::var("V2_COORDINATOR_URL").ok();
        let mut profit_threshold: Option<f64> = None;
        let mut role_action: Option<String> = None;
        let mut own_group_id: Option<String> = None;

        if let Some(ref url) = coordinator_url {
            match crate::v2_coordinator_client::lookup_policy(url, context.own_index.value()) {
                Ok(Some(policy)) => {
                    attack_mode = policy.strategy.clone();
                    attack_type = policy.family.clone();
                    is_attacker = true;
                    attack_active = matches!(
                        attack_mode.as_str(),
                        "fissure" | "speculative" | "sluggish" | "mysticeti_lvw" | "mysticeti_lvw_fissure" | "mysticeti_eclipse" | "mysticeti_eclipse_lvw" | "mysticeti_withhold" | "mysticeti_withhold_lvw" | "mysticeti_slw" | "mysticeti_slw_fissure"
                    );
                    if let Some(v) = policy.params.get("speculative_p_max").and_then(|v| v.as_u64()) {
                        speculative_p_max = v as usize;
                    }
                    if let Some(v) = policy.params.get("sluggish_timeout_multiplier").and_then(|v| v.as_f64()) {
                        sluggish_timeout_multiplier = v;
                    }
                    profit_threshold = policy.params.get("profit_threshold").and_then(|v| v.as_f64());
                    role_action = policy.params.get("role_action").and_then(|v| v.as_str()).map(|s| s.to_string());
                    own_group_id = Some(policy.group_id.clone());
                    info!(
                        "v2 coordinator: node {} assigned policy group={} family={} strategy={}",
                        context.own_index.value(), policy.group_id, policy.family, policy.strategy
                    );
                }
                Ok(None) => {
                    is_attacker = false;
                    attack_active = false;
                    info!(
                        "v2 coordinator: node {} is honest (404)",
                        context.own_index.value()
                    );
                }
                Err(e) => panic!(
                    "v2 coordinator policy lookup failed for node {}: {}",
                    context.own_index.value(), e
                ),
            }
        }

        Self {
            context,
            transaction_consumer,
            transaction_vote_tracker,
            propagation_delay: 0,
            last_included_ancestors,
            block_signer,
            last_known_proposed_round,
            ancestor_state_manager,
            round_tracker,
            dag_state,
            leader_waiter,
            attack_mode,
            attack_type,
            is_attacker,
            attack_active,
            speculative_p_max,
            sluggish_timeout_multiplier,
            coordinator_url,
            profit_threshold,
            role_action,
            own_group_id,
        }
    }

    fn last_proposed_block(&self) -> VerifiedBlock {
        self.dag_state
            .read()
            .get_last_proposed_block()
            .expect("A block should have been returned")
    }

    fn last_proposed_timestamp_ms(&self) -> BlockTimestampMs {
        self.dag_state
            .read()
            .get_last_proposed_block()
            .expect("A block should have been returned")
            .timestamp_ms()
    }

    /// Retrieves the next ancestors to propose to form a block at `clock_round` round.
    /// If smart selection is enabled then this will try to select the best ancestors
    /// based on the propagation scores of the authorities.
    fn smart_ancestors_to_propose(
        &mut self,
        clock_round: Round,
        smart_select: bool,
    ) -> (Vec<VerifiedBlock>, BTreeSet<BlockRef>) {
        let node_metrics = &self.context.metrics.node_metrics;
        let _s = node_metrics
            .scope_processing_time
            .with_label_values(&["ValidatorProposer::smart_ancestors_to_propose"])
            .start_timer();

        // Now take the ancestors before the clock_round (excluded) for each authority.
        let all_ancestors = self
            .dag_state
            .read()
            .get_last_cached_block_per_authority(clock_round);

        assert_eq!(
            all_ancestors.len(),
            self.context.committee.size(),
            "Fatal error, number of returned ancestors don't match committee size."
        );

        // Ensure ancestor state is up to date before selecting for proposal.
        let accepted_quorum_rounds = self.round_tracker.read().compute_accepted_quorum_rounds();

        self.ancestor_state_manager
            .update_all_ancestors_state(&accepted_quorum_rounds);

        let ancestor_state_map = self.ancestor_state_manager.get_ancestor_states();

        let quorum_round = clock_round.saturating_sub(1);

        let mut score_and_pending_excluded_ancestors = Vec::new();
        let mut excluded_and_equivocating_ancestors = BTreeSet::new();

        // Propose only ancestors of higher rounds than what has already been proposed.
        // And always include own last proposed block first among ancestors.
        // Start by only including the high scoring ancestors. Low scoring ancestors
        // will be included in a second pass below.
        let included_ancestors = iter::once(self.last_proposed_block())
            .chain(
                all_ancestors
                    .into_iter()
                    .flat_map(|(ancestor, equivocating_ancestors)| {
                        if ancestor.author() == self.context.own_index {
                            return None;
                        }
                        if let Some(last_block_ref) =
                            self.last_included_ancestors[ancestor.author()]
                            && last_block_ref.round >= ancestor.round() {
                                return None;
                            }

                        // We will never include equivocating ancestors so add them immediately
                        excluded_and_equivocating_ancestors.extend(equivocating_ancestors);

                        let ancestor_state = ancestor_state_map[ancestor.author()];
                        match ancestor_state {
                            AncestorState::Include => {
                                trace!("Found ancestor {ancestor} with INCLUDE state for round {clock_round}");
                            }
                            AncestorState::Exclude(score) => {
                                trace!("Added ancestor {ancestor} with EXCLUDE state with score {score} to temporary excluded ancestors for round {clock_round}");
                                score_and_pending_excluded_ancestors.push((score, ancestor));
                                return None;
                            }
                        }

                        Some(ancestor)
                    }),
            )
            .collect::<Vec<_>>();

        // FISSURE ATTACK: selectively drop victim ancestors from this
        // attacker's parent set. Inert unless ATTACK_MODE=fissure AND
        // this node's index is within the attacker prefix. Backrun and
        // sandwich families (ATTACK_TYPE != "frontrun") share the same
        // hook but invert the rule: hold the proposal until a victim
        // parent appears, then include it (positioning the attacker
        // *after* the victim).
        let included_ancestors =
            self.preprocess_ancestors_for_fissure_attack(included_ancestors, clock_round);

        // MYSTICETI-LVW ATTACK: when this attacker proposes at R+1 and
        // the leader at R is in the victim authority range, drop the
        // victim leader's R block from this attacker's parents. The
        // attacker's R+1 block thereby becomes a "blame" for that
        // leader. The remaining quorum-round ancestors still cover
        // 2f+1 stake (we drop one validator's block out of up to n).
        // See proposer.rs::preprocess_ancestors_for_mysticeti_lvw_attack.
        let included_ancestors =
            self.preprocess_ancestors_for_mysticeti_lvw_attack(included_ancestors, clock_round);

        // When backrun/sandwich is asked to wait for a victim parent
        // and none exists, return empty to defer this round entirely.
        if included_ancestors.is_empty() {
            return (vec![], BTreeSet::new());
        }

        let mut parent_round_quorum = StakeAggregator::<QuorumThreshold>::new();

        // Check total stake of high scoring parent round ancestors
        for ancestor in included_ancestors
            .iter()
            .filter(|a| a.round() == quorum_round)
        {
            parent_round_quorum.add(ancestor.author(), &self.context.committee);
        }

        if smart_select && !parent_round_quorum.reached_threshold(&self.context.committee) {
            node_metrics.smart_selection_wait.inc();
            debug!(
                "Only found {} stake of good ancestors to include for round {clock_round}, will wait for more.",
                parent_round_quorum.stake()
            );
            return (vec![], BTreeSet::new());
        }

        // Sort scores descending so we can include the best of the pending excluded
        // ancestors first until we reach the threshold.
        score_and_pending_excluded_ancestors.sort_by(|a, b| b.0.cmp(&a.0));

        let mut ancestors_to_propose = included_ancestors;
        let mut excluded_ancestors = Vec::new();
        for (score, ancestor) in score_and_pending_excluded_ancestors.into_iter() {
            let block_hostname = &self.context.committee.authority(ancestor.author()).hostname;
            if !parent_round_quorum.reached_threshold(&self.context.committee)
                && ancestor.round() == quorum_round
            {
                debug!(
                    "Including temporarily excluded parent round ancestor {ancestor} with score {score} to propose for round {clock_round}"
                );
                parent_round_quorum.add(ancestor.author(), &self.context.committee);
                ancestors_to_propose.push(ancestor);
                node_metrics
                    .included_excluded_proposal_ancestors_count_by_authority
                    .with_label_values(&[block_hostname.as_str(), "timeout"])
                    .inc();
            } else {
                excluded_ancestors.push((score, ancestor));
            }
        }

        // Iterate through excluded ancestors and include the ancestor or the ancestor's ancestor
        // that has been accepted by a quorum of the network. If the original ancestor itself
        // is not included then it will be part of excluded ancestors that are not
        // included in the block but will still be broadcasted to peers.
        for (score, ancestor) in excluded_ancestors.iter() {
            let excluded_author = ancestor.author();
            let block_hostname = &self.context.committee.authority(excluded_author).hostname;
            // A quorum of validators reported to have accepted blocks from the excluded_author up to the low quorum round.
            let mut accepted_low_quorum_round = accepted_quorum_rounds[excluded_author].0;
            // If the accepted quorum round of this ancestor is greater than or equal
            // to the clock round then we want to make sure to set it to clock_round - 1
            // as that is the max round the new block can include as an ancestor.
            accepted_low_quorum_round = accepted_low_quorum_round.min(quorum_round);

            let last_included_round = self.last_included_ancestors[excluded_author]
                .map(|block_ref| block_ref.round)
                .unwrap_or(GENESIS_ROUND);
            if ancestor.round() <= last_included_round {
                // This should have already been filtered out when filtering all_ancestors.
                // Still, ensure previously included ancestors are filtered out.
                continue;
            }

            if last_included_round >= accepted_low_quorum_round {
                excluded_and_equivocating_ancestors.insert(ancestor.reference());
                trace!(
                    "Excluded low score ancestor {} with score {score} to propose for round {clock_round}: last included round {last_included_round} >= accepted low quorum round {accepted_low_quorum_round}",
                    ancestor.reference()
                );
                node_metrics
                    .excluded_proposal_ancestors_count_by_authority
                    .with_label_values(&[block_hostname])
                    .inc();
                continue;
            }

            let ancestor = if ancestor.round() <= accepted_low_quorum_round {
                // Include the ancestor block as it has been seen & accepted by a strong quorum.
                ancestor.clone()
            } else {
                // Exclude this ancestor since it hasn't been accepted by a strong quorum
                excluded_and_equivocating_ancestors.insert(ancestor.reference());
                trace!(
                    "Excluded low score ancestor {} with score {score} to propose for round {clock_round}: ancestor round {} > accepted low quorum round {accepted_low_quorum_round} ",
                    ancestor.reference(),
                    ancestor.round()
                );
                node_metrics
                    .excluded_proposal_ancestors_count_by_authority
                    .with_label_values(&[block_hostname])
                    .inc();

                // Look for an earlier block in the ancestor chain that we can include as there
                // is a gap between the last included round and the accepted low quorum round.
                //
                // Note: Only cached blocks need to be propagated. Committed and GC'ed blocks
                // do not need to be propagated.
                match self.dag_state.read().get_last_cached_block_in_range(
                    excluded_author,
                    last_included_round + 1,
                    accepted_low_quorum_round + 1,
                ) {
                    Some(earlier_ancestor) => {
                        // Found an earlier block that has been propagated well - include it instead
                        earlier_ancestor
                    }
                    None => {
                        // No suitable earlier block found
                        continue;
                    }
                }
            };
            self.last_included_ancestors[excluded_author] = Some(ancestor.reference());
            ancestors_to_propose.push(ancestor.clone());
            trace!(
                "Included low scoring ancestor {} with score {score} seen at accepted low quorum round {accepted_low_quorum_round} to propose for round {clock_round}",
                ancestor.reference()
            );
            node_metrics
                .included_excluded_proposal_ancestors_count_by_authority
                .with_label_values(&[block_hostname.as_str(), "quorum"])
                .inc();
        }

        assert!(
            parent_round_quorum.reached_threshold(&self.context.committee),
            "Fatal error, quorum not reached for parent round when proposing for round {clock_round}. Possible mismatch between DagState and Core."
        );

        debug!(
            "Included {} ancestors & excluded {} low performing or equivocating ancestors for proposal in round {clock_round}",
            ancestors_to_propose.len(),
            excluded_and_equivocating_ancestors.len()
        );

        (ancestors_to_propose, excluded_and_equivocating_ancestors)
    }

    // === Paper-1 MEV attack helpers ===
    //
    // These are env-var gated. When ATTACK_MODE is unset (or this node is
    // not in the attacker prefix) they return inputs unchanged.

    /// FISSURE family-aware ancestor preprocessing.
    ///
    /// - `ATTACK_TYPE=frontrun` (default): selectively exclude victim
    ///   ancestors from the parent set, biased toward keeping quorum.
    ///   A victim block at the parent round is only dropped when the
    ///   remaining parent-round stake stays above a safe margin over
    ///   quorum, so the resulting choice is one this honest validator
    ///   would also be allowed to make.
    /// - `ATTACK_TYPE=backrun|sandwich`: invert the rule. Wait for a
    ///   victim parent to appear; only then propose, so the attacker
    ///   block lands *after* the victim. If no victim parent is yet
    ///   visible at quorum_round, return empty to defer this round.
    fn preprocess_ancestors_for_fissure_attack(
        &self,
        ancestors: Vec<VerifiedBlock>,
        clock_round: Round,
    ) -> Vec<VerifiedBlock> {
        let fissure_active = matches!(
            self.attack_mode.as_str(),
            "fissure" | "mysticeti_lvw_fissure"
        );
        // Bribed nodes can also run fissure (exclude victim blocks) if
        // listed in FISSURE_BRIBED_NODES. Combined with MLVW bribery
        // this means bribed validators both blame victim leaders AND
        // exclude victim ancestors — double-whammy reducing victim
        // causal-cone inclusion.
        let fissure_bribed = env::var("FISSURE_BRIBED_NODES")
            .ok()
            .map(|s| {
                s.split(',')
                    .filter_map(|t| t.trim().parse::<usize>().ok())
                    .collect::<Vec<_>>()
            })
            .unwrap_or_default();
        let am_fissure_bribed = fissure_bribed.contains(&self.context.own_index.value());

        // v2 honest-side bribery: if this node is listed in V2_BRIBED_HONEST,
        // check the coordinator for pending bribery offers and apply infractions.
        if let Some(ref url) = self.coordinator_url {
            let bribed_honest: Vec<usize> = env::var("V2_BRIBED_HONEST")
                .ok()
                .map(|s| s.split(',').filter_map(|t| t.trim().parse().ok()).collect())
                .unwrap_or_default();
            if !self.is_attacker && bribed_honest.contains(&self.context.own_index.value()) {
                if let Ok(Some(offer)) = crate::v2_coordinator_client::query_pending_bribery_offer(url, self.context.own_index.value()) {
                    if let Ok(true) = crate::v2_coordinator_client::bribery_decide(url, &offer.offer_id, self.context.own_index.value()) {
                        let _ = crate::v2_coordinator_client::bribery_accept(url, &offer.offer_id, self.context.own_index.value());
                        if offer.infraction == "omit_reference" || offer.infraction == "omit_reference_once" {
                            let committee_size = self.context.committee.size();
                            let victim_ratio: f64 = env::var("VICTIM_RATIO").ok().and_then(|s| s.parse().ok()).unwrap_or(0.2);
                            let victim_count = (committee_size as f64 * victim_ratio) as usize;
                            let orig_len = ancestors.len();
                            let filtered: Vec<VerifiedBlock> = ancestors.into_iter().filter(|a| !self.is_victim_block(a, victim_count)).collect();
                            debug!("v2 bribery: honest node {} applied omit_reference, dropped {} ancestors", self.context.own_index.value(), orig_len - filtered.len());
                            return filtered;
                        }
                    }
                }
            }
        }

        if !fissure_active || (!self.is_attacker && !am_fissure_bribed) {
            return ancestors;
        }

        // v2 coordinator: per-round coordination decision (role dispatch +
        // shared exclusion seed for P3 collusion experiments).
        if let Some(ref url) = self.coordinator_url {
            if let Ok(decision) = crate::v2_coordinator_client::query_coordinate_decision(url, self.context.own_index.value(), clock_round as u64) {
                if let Some(ref role) = decision.role {
                    if role == "passive" {
                        return ancestors;
                    }
                }
            }
        }

        let committee_size = self.context.committee.size();
        let victim_ratio: f64 = env::var("VICTIM_RATIO")
            .ok()
            .and_then(|s| s.parse().ok())
            .unwrap_or(0.2);
        let attacker_ratio: f64 = env::var("ATTACKER_RATIO")
            .ok()
            .and_then(|s| s.parse().ok())
            .unwrap_or(0.33);
        let victim_count = (committee_size as f64 * victim_ratio) as usize;
        let attacker_count = (committee_size as f64 * attacker_ratio) as usize;
        let quorum_round = clock_round.saturating_sub(1);

        if self.attack_type != "frontrun" {
            // Backrun / sandwich: only propose if a victim parent is
            // already in the parent round. Otherwise defer.
            let victim_parent_present = ancestors.iter().any(|ancestor| {
                ancestor.round() == quorum_round && self.is_victim_block(ancestor, victim_count)
            });
            if !victim_parent_present {
                debug!(
                    "Backrun/sandwich: deferring proposal at round {clock_round}, no victim parent yet"
                );
                return vec![];
            }
            return ancestors;
        }

        // Frontrun: drop victim ancestors when safe to do so.
        let mut parent_round_stake: u64 = 0;
        for ancestor in ancestors.iter() {
            if ancestor.round() == quorum_round {
                parent_round_stake += self.context.committee.stake(ancestor.author());
            }
        }
        let quorum_threshold = self.context.committee.quorum_threshold();
        let safe_margin = quorum_threshold + (quorum_threshold / 5);

        let exclusion_prob = self.calculate_exclusion_probability(
            attacker_count,
            victim_count,
            committee_size,
        );

        let mut filtered = Vec::with_capacity(ancestors.len());
        let mut excluded = 0usize;
        for ancestor in ancestors {
            let is_victim = self.is_victim_block(&ancestor, victim_count);
            if !is_victim {
                filtered.push(ancestor);
                continue;
            }

            let ancestor_stake = self.context.committee.stake(ancestor.author());
            let is_parent_round = ancestor.round() == quorum_round;
            let should_exclude = if is_parent_round {
                let remaining = parent_round_stake.saturating_sub(ancestor_stake);
                let prob = if remaining >= safe_margin {
                    exclusion_prob
                } else if remaining >= quorum_threshold {
                    exclusion_prob * 0.5
                } else {
                    0.0
                };
                self.should_exclude_victim_block(&ancestor, prob)
            } else {
                self.should_exclude_victim_block(&ancestor, exclusion_prob.min(0.98))
            };

            if should_exclude {
                excluded += 1;
                if is_parent_round {
                    parent_round_stake = parent_round_stake.saturating_sub(ancestor_stake);
                }
                trace!(
                    "Fissure: excluding victim ancestor {} at round {}",
                    ancestor.reference(),
                    ancestor.round()
                );
                continue;
            }
            filtered.push(ancestor);
        }

        if excluded > 0 {
            debug!(
                "Fissure: excluded {excluded} victim ancestor(s) at round {clock_round}"
            );
        }
        filtered
    }

    /// Victims are the last `victim_count` authority indices.
    fn is_victim_block(&self, block: &VerifiedBlock, victim_count: usize) -> bool {
        let author = block.author().value();
        let n = self.context.committee.size();
        victim_count > 0 && author >= n.saturating_sub(victim_count)
    }

    /// MYSTICETI Leader-Vote Withholding (MLVW) preprocess.
    ///
    /// Mysticeti's direct-commit rule for a leader L at round R needs at
    /// least one block at decision_round (R + wave_length - 1) whose
    /// causal history contains 2f+1 distinct authority "votes" for L.
    /// A "vote" is a R+1 block that includes L's R block transitively
    /// as the first (author, round) match in its ancestor set
    /// (base_committer::find_supported_block, is_vote).
    ///
    /// When this attacker proposes its own block at round R+1 and the
    /// leader at R is in the victim authority range, dropping the
    /// victim leader's R block from this attacker's parent set makes
    /// the resulting block a "blame" for that leader. The remaining
    /// round-R ancestors still satisfy the parent-round quorum
    /// (12 of 13 authorities, well above 2f+1 = 9).
    ///
    /// Honest validators are unmodified; this stays inside the
    /// honest-action set (a slow validator could legitimately miss
    /// the leader's block and propose without it). Inert unless
    /// ATTACK_MODE=mysticeti_lvw AND this node is in the attacker
    /// prefix.
    fn preprocess_ancestors_for_mysticeti_lvw_attack(
        &self,
        ancestors: Vec<VerifiedBlock>,
        clock_round: Round,
    ) -> Vec<VerifiedBlock> {
        // The hook fires for the attacker prefix OR for nodes explicitly
        // listed in MLVW_BRIBED_NODES (comma-separated authority
        // indices). Bribery simulation: a bribed honest validator's
        // R+1 block also withholds its vote from victim leaders.
        let bribed = env::var("MLVW_BRIBED_NODES")
            .ok()
            .map(|s| {
                s.split(',')
                    .filter_map(|t| t.trim().parse::<usize>().ok())
                    .collect::<Vec<_>>()
            })
            .unwrap_or_default();
        let own_idx = self.context.own_index.value();
        let am_bribed = bribed.contains(&own_idx);
        let mlvw_active = self.attack_mode.contains("lvw")
            || self.attack_mode.contains("eclipse");
        if !mlvw_active || (!self.is_attacker && !am_bribed) {
            return ancestors;
        }

        // v2 coordinator: per-round role dispatch for MLVW.
        if let Some(ref url) = self.coordinator_url {
            if let Ok(decision) = crate::v2_coordinator_client::query_coordinate_decision(url, own_idx, clock_round as u64) {
                if let Some(ref role) = decision.role {
                    if role == "passive" {
                        return ancestors;
                    }
                }
            }
        }

        // The leader round being voted on is clock_round - 1.
        let leader_round = clock_round.saturating_sub(1);
        if leader_round == 0 {
            return ancestors;
        }

        let committee_size = self.context.committee.size();
        let victim_ratio: f64 = env::var("VICTIM_RATIO")
            .ok()
            .and_then(|s| s.parse().ok())
            .unwrap_or(0.231);
        let victim_count = (committee_size as f64 * victim_ratio).round() as usize;
        if victim_count == 0 {
            return ancestors;
        }
        let victim_first_idx = committee_size.saturating_sub(victim_count);

        // Pipelined commit uses up to wave_length committers, each with
        // a different leader_offset. Build the candidate victim-leader
        // authorities for this leader_round under the for_testing
        // round-robin scheme: authority = (leader_round + offset) %
        // committee_size for offset in 0..wave_length.
        let wave_length = crate::commit::DEFAULT_WAVE_LENGTH as usize;
        let attacker_ratio: f64 = env::var("ATTACKER_RATIO")
            .ok()
            .and_then(|s| s.parse().ok())
            .unwrap_or(0.308);
        let attacker_count = (committee_size as f64 * attacker_ratio).floor() as usize;
        // MLVW_BLAME_ALL_NON_ATTACKER: when set, attackers blame ALL
        // non-attacker leaders (not just victim-authority leaders).
        // With f > n/3 this monopolizes commit certification for
        // attacker-led rounds only. Models "full Byzantine bribery"
        // where the bribed validator acts as a complete attacker.
        let blame_all = env::var("MLVW_BLAME_ALL_NON_ATTACKER")
            .ok()
            .filter(|v| v != "0")
            .is_some();
        let mut victim_authorities: Vec<usize> = Vec::with_capacity(wave_length);
        for offset in 0..wave_length {
            let auth = (leader_round as usize + offset) % committee_size;
            let is_target = if blame_all {
                auth >= attacker_count
            } else {
                auth >= victim_first_idx
            };
            if is_target {
                victim_authorities.push(auth);
            }
        }
        if victim_authorities.is_empty() {
            return ancestors;
        }

        let mut dropped = 0usize;
        let filtered: Vec<VerifiedBlock> = ancestors
            .into_iter()
            .filter(|a| {
                let is_victim_leader_at_leader_round = a.round() == leader_round
                    && victim_authorities.contains(&a.author().value());
                if is_victim_leader_at_leader_round {
                    dropped += 1;
                    trace!(
                        "MLVW: dropping victim-leader block {} from parent set at clock_round {}",
                        a.reference(),
                        clock_round
                    );
                    false
                } else {
                    true
                }
            })
            .collect();
        if dropped > 0 {
            debug!(
                "MLVW: dropped {dropped} victim-leader ancestor(s) at clock_round {clock_round} (leader_round {leader_round}, victim_authorities={victim_authorities:?})"
            );
        }
        filtered
    }

    /// Paper-1 baseline equation: Pfis0 = 1/2 + fa / (2 (n - fl)),
    /// scaled by a network-size factor and capped at 0.95.
    fn calculate_exclusion_probability(
        &self,
        attacker_count: usize,
        victim_count: usize,
        committee_size: usize,
    ) -> f64 {
        let fa = attacker_count as f64;
        let fl = victim_count as f64;
        let n = committee_size as f64;
        let base = 0.5 + fa / (2.0 * (n - fl).max(1.0));
        let network_factor = if n <= 13.0 { 7.0 } else { 6.5 };
        (base * network_factor).min(0.95)
    }

    /// Deterministic exclusion coin derived from the block reference, so
    /// all attackers flip the same coin for the same block without any
    /// out-of-band coordination.
    fn should_exclude_victim_block(
        &self,
        block: &VerifiedBlock,
        exclusion_prob: f64,
    ) -> bool {
        if exclusion_prob <= 0.0 {
            return false;
        }
        let block_ref = block.reference();
        let digest_bytes: &[u8] = block_ref.digest.as_ref();
        let mut seed: u64 = 0;
        for (i, &byte) in digest_bytes.iter().take(8).enumerate() {
            seed ^= (byte as u64) << (i * 8);
        }
        seed = seed.wrapping_add(block_ref.round as u64 * 31);
        seed = seed.wrapping_add(block_ref.author.value() as u64 * 17);
        let r = (seed % 10_000) as f64 / 10_000.0;
        r < exclusion_prob
    }
}

impl Proposer for ValidatorProposer {
    fn try_new_block(&mut self, force: bool) -> Option<ExtendedBlock> {
        // SLUGGISH ATTACK: deliberately delay proposal for attackers.
        // The delay is a multiple of leader_timeout, which is a knob an
        // honest validator with a slow link could legitimately match.
        if self.attack_active && self.is_attacker && self.attack_mode == "sluggish" {
            let base_timeout_ms = self.context.parameters.leader_timeout.as_millis() as f64;
            let delay_ms = (base_timeout_ms * self.sluggish_timeout_multiplier) as u64;
            debug!(
                "Sluggish: node {} delaying proposal by {}ms ({}x leader_timeout={}ms)",
                self.context.own_index.value(),
                delay_ms,
                self.sluggish_timeout_multiplier,
                base_timeout_ms,
            );
            std::thread::sleep(Duration::from_millis(delay_ms));
        }

        // STRATEGIC LEADER WITHHOLDING (SLW): when this attacker IS the
        // leader for the current round, SKIP proposing entirely. Other
        // validators will timeout (leader_timeout) and propose at the
        // next round with force=true. The attacker's leader round gets
        // skipped via indirect decision → blocks from that wave merge
        // into the next leader's subdag, changing subdag boundaries.
        // Non-leader rounds are proposed normally.
        if self.attack_active && self.is_attacker
            && (self.attack_mode.contains("slw"))
        {
            let clock_round = self.dag_state.read().threshold_clock_round();
            let committee_size = self.context.committee.size();
            let is_my_leader_round = (clock_round as usize % committee_size) == self.context.own_index.value();
            if is_my_leader_round {
                debug!(
                    "SLW: node {} SKIPPING leader proposal at round {}",
                    self.context.own_index.value(), clock_round
                );
                return None;
            }
        }

        if !self.should_propose() {
            return None;
        }

        let _s = self
            .context
            .metrics
            .node_metrics
            .scope_processing_time
            .with_label_values(&["ValidatorProposer::try_new_block"])
            .start_timer();

        // Ensure the new block has a higher round than the last proposed block.
        let clock_round = {
            let dag_state = self.dag_state.read();
            let clock_round = dag_state.threshold_clock_round();
            if clock_round
                <= dag_state
                    .get_last_proposed_block()
                    .expect("A block should have been returned")
                    .round()
            {
                debug!(
                    "Skipping block proposal for round {} as it is not higher than the last proposed block {}",
                    clock_round,
                    dag_state
                        .get_last_proposed_block()
                        .expect("A block should have been returned")
                        .round()
                );
                return None;
            }
            clock_round
        };

        // There must be a quorum of blocks from the previous round.
        let quorum_round = clock_round.saturating_sub(1);
        let leader_slots = self.leader_waiter.leader_slots_to_wait_for(quorum_round);

        // Create a new block either because we want to "forcefully" propose a block due to a leader timeout,
        // or because we are actually ready to produce the block (leader exists and min delay has passed).
        if !force {
            {
                let dag_state = self.dag_state.read();
                if !leader_slots
                    .iter()
                    .all(|slot| dag_state.contains_cached_block_at_slot(*slot))
                {
                    return None;
                }
            }

            if Duration::from_millis(
                self.context
                    .clock
                    .timestamp_utc_ms()
                    .saturating_sub(self.last_proposed_timestamp_ms()),
            ) < self.context.parameters.min_round_delay
            {
                debug!(
                    "Skipping block proposal for round {} as it is too soon after the last proposed block timestamp {}; min round delay is {}ms",
                    clock_round,
                    self.last_proposed_timestamp_ms(),
                    self.context.parameters.min_round_delay.as_millis(),
                );
                return None;
            }
        }

        // Determine the ancestors to be included in proposal.
        let (ancestors, excluded_and_equivocating_ancestors) =
            self.smart_ancestors_to_propose(clock_round, !force);

        // If we did not find enough good ancestors to propose, continue to wait before proposing.
        if ancestors.is_empty() {
            assert!(
                !force,
                "Ancestors should have been returned if force is true!"
            );
            debug!(
                "Skipping block proposal for round {} because no good ancestor is found",
                clock_round,
            );
            return None;
        }

        let excluded_ancestors_limit = self.context.committee.size() * 2;
        if excluded_and_equivocating_ancestors.len() > excluded_ancestors_limit {
            debug!(
                "Dropping {} excluded ancestor(s) during proposal due to size limit",
                excluded_and_equivocating_ancestors.len() - excluded_ancestors_limit,
            );
        }
        let excluded_ancestors = excluded_and_equivocating_ancestors
            .into_iter()
            .take(excluded_ancestors_limit)
            .collect();

        // Update the last included ancestor block refs
        for ancestor in &ancestors {
            self.last_included_ancestors[ancestor.author()] = Some(ancestor.reference());
        }

        // TODO(v3): support these metrics under v3 multi leader logic:
        // - Leader slots are empty when the quorum round is no greater than last committed leader round,
        //   because of async process or recovery.
        // - Record accepted time for each block, to decide the last leader and the amount of time waiting for it.
        if !self.context.protocol_config.enable_v3() {
            let leader_slot = leader_slots.first().unwrap();
            let leader_authority = &self
                .context
                .committee
                .authority(leader_slot.authority)
                .hostname;
            self.context
                .metrics
                .node_metrics
                .block_proposal_leader_wait_ms
                .with_label_values(&[leader_authority])
                .inc_by(
                    Instant::now()
                        .saturating_duration_since(
                            self.dag_state.read().threshold_clock_quorum_ts(),
                        )
                        .as_millis() as u64,
                );
            self.context
                .metrics
                .node_metrics
                .block_proposal_leader_wait_count
                .with_label_values(&[leader_authority])
                .inc();
        }

        self.context
            .metrics
            .node_metrics
            .proposed_block_ancestors
            .observe(ancestors.len() as f64);
        for ancestor in &ancestors {
            let authority = &self.context.committee.authority(ancestor.author()).hostname;
            self.context
                .metrics
                .node_metrics
                .proposed_block_ancestors_depth
                .with_label_values(&[authority])
                .observe(clock_round.saturating_sub(ancestor.round()).into());
        }

        let now = self.context.clock.timestamp_utc_ms();
        ancestors.iter().for_each(|block| {
            if block.timestamp_ms() > now {
                trace!("Ancestor block {:?} has timestamp {}, greater than current timestamp {now}. Proposing for round {}.", block, block.timestamp_ms(), clock_round);
                let authority = &self.context.committee.authority(block.author()).hostname;
                self.context
                    .metrics
                    .node_metrics
                    .proposed_block_ancestors_timestamp_drift_ms
                    .with_label_values(&[authority])
                    .inc_by(block.timestamp_ms().saturating_sub(now));
            }
        });

        // Consume the next transactions to be included. Do not drop the guards yet as this would acknowledge
        // the inclusion of transactions. Just let this be done in the end of the method.
        let (transactions, ack_transactions, _limit_reached) = self.transaction_consumer.next();
        self.context
            .metrics
            .node_metrics
            .proposed_block_transactions
            .observe(transactions.len() as f64);

        // Consume the commit votes to be included.
        let commit_votes = self
            .dag_state
            .write()
            .take_commit_votes(MAX_COMMIT_VOTES_PER_BLOCK);

        let transaction_votes = if self.context.protocol_config.transaction_voting_enabled() {
            let new_causal_history = {
                let mut dag_state = self.dag_state.write();
                ancestors
                    .iter()
                    .flat_map(|ancestor| dag_state.link_causal_history(ancestor.reference()))
                    .collect()
            };
            self.transaction_vote_tracker
                .get_own_votes(new_causal_history)
        } else {
            vec![]
        };

        // SPECULATIVE ATTACK: enumerate up to p_max deterministic
        // transaction reorderings/truncations and keep the candidate
        // whose serialized block hash is lexicographically largest.
        // Choosing which valid block to propose is an attacker-legal
        // action — the candidates are all individually well-formed.
        let mut final_transactions = transactions;
        if self.attack_active && self.is_attacker && self.attack_mode == "speculative" {
            use consensus_types::block::BlockDigest;
            let p_max = self.speculative_p_max.min(50);
            let mut best_digest: Option<BlockDigest> = None;
            let mut best_transactions = final_transactions.clone();
            let mut candidate = final_transactions.clone();
            for i in 0..p_max {
                let len = candidate.len();
                if len > 0 {
                    candidate.rotate_right(i % len);
                }
                if i % 3 == 0 && candidate.len() > 1 {
                    let keep = ((candidate.len() as f64) * 0.9).ceil() as usize;
                    candidate.truncate(keep.max(1));
                }
                let trial_block = if self.context.protocol_config.transaction_voting_enabled() {
                    Block::V2(BlockV2::new(
                        self.context.committee.epoch(),
                        clock_round,
                        self.context.own_index,
                        now,
                        ancestors.iter().map(|b| b.reference()).collect(),
                        candidate.clone(),
                        transaction_votes.clone(),
                        commit_votes.clone(),
                        vec![],
                    ))
                } else {
                    Block::V1(BlockV1::new(
                        self.context.committee.epoch(),
                        clock_round,
                        self.context.own_index,
                        now,
                        ancestors.iter().map(|b| b.reference()).collect(),
                        candidate.clone(),
                        commit_votes.clone(),
                        vec![],
                    ))
                };
                let signed = SignedBlock::new(trial_block, &self.block_signer)
                    .expect("trial block signing");
                let bytes = signed.serialize().expect("trial block serialize");
                let digest = VerifiedBlock::compute_digest(&bytes);
                let take = match &best_digest {
                    None => true,
                    Some(cur) => digest > *cur,
                };
                if take {
                    best_digest = Some(digest);
                    best_transactions = candidate.clone();
                }
            }
            debug!(
                "Speculative: node {} picked best of {} candidates",
                self.context.own_index.value(),
                p_max,
            );
            final_transactions = best_transactions;
        }

        // Create the block.
        let block = if self.context.protocol_config.transaction_voting_enabled() {
            Block::V2(BlockV2::new(
                self.context.committee.epoch(),
                clock_round,
                self.context.own_index,
                now,
                ancestors.iter().map(|b| b.reference()).collect(),
                final_transactions,
                transaction_votes,
                commit_votes,
                vec![],
            ))
        } else {
            Block::V1(BlockV1::new(
                self.context.committee.epoch(),
                clock_round,
                self.context.own_index,
                now,
                ancestors.iter().map(|b| b.reference()).collect(),
                final_transactions,
                commit_votes,
                vec![],
            ))
        };
        let signed_block =
            SignedBlock::new(block, &self.block_signer).expect("Block signing failed.");
        let serialized = signed_block
            .serialize()
            .expect("Block serialization failed.");
        self.context
            .metrics
            .node_metrics
            .proposed_block_size
            .observe(serialized.len() as f64);
        // Own blocks are assumed to be valid.
        let verified_block = VerifiedBlock::new_verified(signed_block, serialized);

        // Record the interval from last proposal.
        let last_proposed_block = self.last_proposed_block();
        if last_proposed_block.round() > 0 {
            self.context
                .metrics
                .node_metrics
                .block_proposal_interval
                .observe(
                    Duration::from_millis(
                        verified_block
                            .timestamp_ms()
                            .saturating_sub(last_proposed_block.timestamp_ms()),
                    )
                    .as_secs_f64(),
                );
        }

        // Add the block directly to DagState (skipping BlockManager since our own blocks cannot be suspended)
        self.dag_state.write().accept_block(verified_block.clone());

        // Update proposed state of blocks in local DAG.
        if self.context.protocol_config.transaction_voting_enabled() {
            self.transaction_vote_tracker
                .add_voted_blocks(vec![(verified_block.clone(), vec![])]);
            // Set the proposed block to be linked. Linked statuses of its ancestors have already been set.
            self.dag_state
                .write()
                .link_causal_history(verified_block.reference());
        }

        // Ensure the new block and its ancestors are persisted, before broadcasting it.
        self.dag_state.write().flush();

        // Now acknowledge the transactions for their inclusion to block
        ack_transactions(verified_block.reference());

        info!("Created block {verified_block:?} for round {clock_round}");

        self.context
            .metrics
            .node_metrics
            .proposed_blocks
            .with_label_values(&[&force.to_string()])
            .inc();

        let extended_block = ExtendedBlock {
            block: verified_block,
            excluded_ancestors,
        };

        // Update round tracker with our own highest accepted blocks
        self.round_tracker
            .write()
            .update_from_verified_block(&extended_block);

        Some(extended_block)
    }

    fn should_propose(&self) -> bool {
        let clock_round = self.dag_state.read().threshold_clock_round();
        let core_skipped_proposals = &self.context.metrics.node_metrics.core_skipped_proposals;

        if self.propagation_delay
            > self
                .context
                .parameters
                .propagation_delay_stop_proposal_threshold
        {
            debug!(
                "Skip proposing for round {clock_round}, high propagation delay {} > {}.",
                self.propagation_delay,
                self.context
                    .parameters
                    .propagation_delay_stop_proposal_threshold
            );
            core_skipped_proposals
                .with_label_values(&["high_propagation_delay"])
                .inc();
            return false;
        }

        let Some(last_known_proposed_round) = self.last_known_proposed_round else {
            debug!(
                "Skip proposing for round {clock_round}, last known proposed round has not been synced yet."
            );
            core_skipped_proposals
                .with_label_values(&["no_last_known_proposed_round"])
                .inc();
            return false;
        };
        if clock_round <= last_known_proposed_round {
            debug!(
                "Skip proposing for round {clock_round} as last known proposed round is {last_known_proposed_round}"
            );
            core_skipped_proposals
                .with_label_values(&["higher_last_known_proposed_round"])
                .inc();
            return false;
        }

        true
    }

    fn set_propagation_delay(&mut self, delay: Round) {
        self.propagation_delay = delay;
    }

    fn set_last_known_proposed_round(&mut self, round: Round) {
        self.last_known_proposed_round = Some(round);
    }

    fn get_last_known_proposed_round(&self) -> Option<Round> {
        self.last_known_proposed_round
    }

    fn last_proposed_round(&self) -> Round {
        self.dag_state
            .read()
            .get_last_proposed_block()
            .expect("A block should have been returned")
            .round()
    }

    fn last_proposed_block(&self) -> VerifiedBlock {
        self.dag_state
            .read()
            .get_last_proposed_block()
            .expect("A block should have been returned")
    }

    fn set_propagation_scores(&mut self, scores: crate::leader_scoring::ReputationScores) {
        self.ancestor_state_manager.set_propagation_scores(scores);
    }

    fn set_next_commit_leader_schedule(&mut self, schedule: NextCommitLeaderSchedule) {
        self.leader_waiter.update_v3_schedule(schedule);
    }

    fn notify_own_blocks_committed(&self, block_refs: Vec<BlockRef>, gc_round: Round) {
        self.transaction_consumer
            .notify_own_blocks_status(block_refs, gc_round);
    }

    #[cfg(test)]
    fn round_tracker_for_tests(&self) -> Arc<RwLock<RoundTracker>> {
        self.round_tracker.clone()
    }
}

/// Determines the identity and set of leaders to wait for from leader schedule,
/// when proposing a block.
pub(crate) enum ProposalLeaderWaiter {
    V2(Arc<UniversalCommitter>),
    V3(NextCommitLeaderSchedule),
}

impl ProposalLeaderWaiter {
    fn leader_slots_to_wait_for(&self, round: Round) -> Vec<Slot> {
        match self {
            Self::V2(committer) => committer
                .get_leaders(round)
                .into_iter()
                .map(|authority_index| Slot::new(round, authority_index))
                .collect(),
            Self::V3(schedule) => {
                if round < schedule.min_next_leader_round {
                    return vec![];
                }
                schedule
                    .allowed_leaders
                    .iter()
                    .map(|leader| Slot::new(round, *leader))
                    .collect()
            }
        }
    }

    #[allow(dead_code)]
    fn update_v3_schedule(&mut self, schedule: NextCommitLeaderSchedule) {
        if let Self::V3(current) = self {
            *current = schedule;
        }
    }
}

#[cfg(test)]
mod tests {
    use consensus_config::AuthorityIndex;

    use super::*;

    #[test]
    fn proposal_leader_waiter_v3_uses_and_updates_schedule() {
        let mut waiter = ProposalLeaderWaiter::V3(NextCommitLeaderSchedule {
            next_commit_index: 1,
            min_next_leader_round: 4,
            allowed_leaders: vec![
                AuthorityIndex::new_for_test(0),
                AuthorityIndex::new_for_test(2),
            ],
        });

        assert!(waiter.leader_slots_to_wait_for(3).is_empty());
        assert_eq!(
            waiter.leader_slots_to_wait_for(4),
            vec![
                Slot::new(4, AuthorityIndex::new_for_test(0)),
                Slot::new(4, AuthorityIndex::new_for_test(2)),
            ]
        );

        waiter.update_v3_schedule(NextCommitLeaderSchedule {
            next_commit_index: 2,
            min_next_leader_round: 4,
            allowed_leaders: vec![
                AuthorityIndex::new_for_test(1),
                AuthorityIndex::new_for_test(3),
            ],
        });

        assert_eq!(
            waiter.leader_slots_to_wait_for(4),
            vec![
                Slot::new(4, AuthorityIndex::new_for_test(1)),
                Slot::new(4, AuthorityIndex::new_for_test(3)),
            ]
        );
    }
}
