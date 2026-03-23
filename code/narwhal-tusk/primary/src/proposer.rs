// Copyright(C) Facebook, Inc. and its affiliates.
use crate::messages::{Certificate, Header};
use crate::primary::Round;
use config::{Committee, WorkerId};
use crypto::Hash;
use crypto::{Digest, PublicKey, SignatureService};
use log::{debug, info, warn};
use std::convert::TryInto;
use tokio::sync::mpsc::{Receiver, Sender};
use tokio::time::{sleep, Duration, Instant};
use std::collections::HashSet;
use std::env;

#[cfg(test)]
#[path = "tests/proposer_tests.rs"]
pub mod proposer_tests;

/// The proposer creates new headers and send them to the core for broadcasting and further processing.
pub struct Proposer {
    /// The public key of this primary.
    name: PublicKey,
    /// Service to sign headers.
    signature_service: SignatureService,
    /// The size of the headers' payload.
    header_size: usize,
    /// The maximum delay to wait for batches' digests.
    max_header_delay: u64,

    /// Receives the parents (digest, origin) to include in the next header (along with their round number).
    rx_core: Receiver<(Vec<(Digest, PublicKey)>, Round)>,
    /// Receives the batches' digests from our workers.
    rx_workers: Receiver<(Digest, WorkerId)>,
    /// Receives notifications that a victim header was observed in this round.
    rx_victim_round: Receiver<Round>,
    /// Sends newly created headers to the `Core`.
    tx_core: Sender<Header>,

    /// The current round of the dag.
    round: Round,
    /// Holds the certificates' (digest, origin) waiting to be included in the next header.
    last_parents: Vec<(Digest, PublicKey)>,
    /// Holds the batches' digests waiting to be included in the next header.
    digests: Vec<(Digest, WorkerId)>,
    /// Keeps track of the size (in bytes) of batches' digests that we received so far.
    payload_size: usize,

    /// Attack configuration
    is_attacker: bool,
    attacker_nodes: HashSet<PublicKey>,
    victim_nodes: HashSet<PublicKey>,
    attack_active: bool,
    attack_mode: String, // "fissure" or "speculative"
    committee_size: usize, // Total number of nodes in committee
    
    /// Attack metrics
    total_rounds: u64,
    successful_exclusions: u64,
    total_victim_blocks: u64,
    
    /// Speculative attack specific
    speculative_attempts: u64,
    speculative_successes: u64,
    speculative_p_max: usize,

    /// Sluggish attack specific (Liveness-aware)
    honest_round: Round,
    sluggish_timeout_multiplier: f64,
    proposed_this_round: bool,
    victim_observed_round: Option<Round>,
    victim_observed_at: Option<Instant>,
    speculative_grace_ms: u64,
    speculative_refresh_parents: bool,
    speculative_require_victim: bool,
}

impl Proposer {
    #[allow(clippy::too_many_arguments)]
    pub fn spawn(
        name: PublicKey,
        committee: &Committee,
        signature_service: SignatureService,
        header_size: usize,
        max_header_delay: u64,
        rx_core: Receiver<(Vec<(Digest, PublicKey)>, Round)>,
        rx_workers: Receiver<(Digest, WorkerId)>,
        rx_victim_round: Receiver<Round>,
        tx_core: Sender<Header>,
    ) {
        // Genesis certificates - use dummy origin since these are special
        let genesis: Vec<(Digest, PublicKey)> = Certificate::genesis(committee)
            .iter()
            .map(|x| (x.digest(), x.origin()))
            .collect();

        // Initialize attack configuration from environment variables
        let attack_mode = env::var("ATTACK_MODE").unwrap_or_default();
        let committee_size = committee.authorities.len();
        let attacker_ratio: f64 = env::var("ATTACKER_RATIO").unwrap_or_default().parse().unwrap_or(0.33);
        let victim_ratio: f64 = env::var("VICTIM_RATIO").unwrap_or_default().parse().unwrap_or(0.22);
        let speculative_p_max: usize = env::var("SPECULATIVE_P_MAX").unwrap_or_default().parse().unwrap_or(10);
        let speculative_grace_ms: u64 = env::var("SPECULATIVE_GRACE_MS")
            .unwrap_or_else(|_| "15".to_string())
            .parse()
            .unwrap_or(15);
        let speculative_refresh_parents = env::var("SPECULATIVE_REFRESH_PARENTS")
            .map(|value| matches!(value.as_str(), "1" | "true" | "TRUE" | "yes" | "YES"))
            .unwrap_or(false);
        let speculative_require_victim = env::var("SPECULATIVE_REQUIRE_VICTIM")
            .map(|value| matches!(value.as_str(), "1" | "true" | "TRUE" | "yes" | "YES"))
            .unwrap_or(committee_size >= 25);
        let sluggish_timeout_multiplier: f64 = env::var("SLUGGISH_TIMEOUT_MULTIPLIER").unwrap_or_else(|_| "2.0".to_string()).parse().unwrap_or(2.0);
        
        let is_attacker = (attack_mode == "fissure" || attack_mode == "speculative" || attack_mode == "sluggish") && Self::is_attacker_node(&name, committee, attacker_ratio);
        let attacker_nodes = Self::get_attacker_nodes(committee, attacker_ratio);
        let victim_nodes = Self::get_victim_nodes(committee, attacker_ratio, victim_ratio);
        let attack_active = attack_mode == "fissure" || attack_mode == "speculative" || attack_mode == "sluggish";

        // Sluggish attack: increase max_header_delay to intentionally delay proposals
        let mut delay = max_header_delay;
        if attack_mode == "sluggish" && is_attacker {
            delay = (max_header_delay as f64 * sluggish_timeout_multiplier) as u64;
            info!("Sluggish attack: Node {} using modified timeout: {}ms (multiplier: {})", name, delay, sluggish_timeout_multiplier);
        }
        let max_header_delay = delay;

        tokio::spawn(async move {
            Self {
                name,
                signature_service,
                header_size,
                max_header_delay,
                rx_core,
                rx_workers,
                rx_victim_round,
                tx_core,
                round: 1,
                last_parents: genesis,
                digests: Vec::with_capacity(2 * header_size),
                payload_size: 0,
                is_attacker,
                attacker_nodes,
                victim_nodes,
                attack_active,
                attack_mode: attack_mode.clone(),
                committee_size,
                total_rounds: 0,
                successful_exclusions: 0,
                total_victim_blocks: 0,
                speculative_attempts: 0,
                speculative_successes: 0,
                speculative_p_max,
                honest_round: 0,
                sluggish_timeout_multiplier,
                proposed_this_round: false,
                victim_observed_round: None,
                victim_observed_at: None,
                speculative_grace_ms,
                speculative_refresh_parents,
                speculative_require_victim,
            }
            .run()
            .await;
        });
    }

    /// Check if this node is an attacker based on configuration
    fn is_attacker_node(name: &PublicKey, committee: &Committee, attacker_ratio: f64) -> bool {
        let total_nodes = committee.authorities.len();
        let attacker_count = (total_nodes as f64 * attacker_ratio) as usize;
        
        // Get sorted list of node names for consistent attacker selection
        let mut node_names: Vec<_> = committee.authorities.keys().collect();
        node_names.sort();
        
        info!("PROPOSER: Node {} checking if attacker. Total nodes: {}, Attacker count: {}", name, total_nodes, attacker_count);
        info!("PROPOSER: Sorted node names: {:?}", node_names);
        info!("PROPOSER: First {} nodes as attackers: {:?}", attacker_count, &node_names[..attacker_count]);
        
        // First N nodes are attackers
        let is_attacker = node_names.iter().take(attacker_count).any(|&node_name| node_name == name);
        info!("PROPOSER: Node {} is attacker: {}", name, is_attacker);
        
        is_attacker
    }

    /// Get set of attacker nodes
    fn get_attacker_nodes(committee: &Committee, attacker_ratio: f64) -> HashSet<PublicKey> {
        let total_nodes = committee.authorities.len();
        let attacker_count = (total_nodes as f64 * attacker_ratio) as usize;
        
        let mut node_names: Vec<_> = committee.authorities.keys().collect();
        node_names.sort();
        
        node_names.iter().take(attacker_count).map(|&k| k.clone()).collect()
    }

    /// Get set of victim nodes
    fn get_victim_nodes(committee: &Committee, attacker_ratio: f64, victim_ratio: f64) -> HashSet<PublicKey> {
        let total_nodes = committee.authorities.len();
        let attacker_count = (total_nodes as f64 * attacker_ratio) as usize;
        let victim_count = env::var("VICTIM_COUNT")
            .ok()
            .and_then(|value| value.parse::<usize>().ok())
            .unwrap_or_else(|| (total_nodes as f64 * victim_ratio) as usize)
            .min(total_nodes.saturating_sub(attacker_count));
        
        let mut node_names: Vec<_> = committee.authorities.keys().collect();
        node_names.sort();
        
        // Victims are the nodes after attackers
        node_names.iter()
            .skip(attacker_count)
            .take(victim_count)
            .map(|&k| k.clone())
            .collect()
    }

    /// Fissure attack pre-processing as described in the research
    /// "omit victim parents" - attackers exclude victim blocks from parent set
    /// CRITICAL: Maintain minimum parent count (2f+1) to ensure block validity
    fn preprocess_parents_for_attack(&mut self, parents: Vec<Digest>) -> Vec<Digest> {
        let total_parents = parents.len();
        
        // Calculate minimum required parents for consensus validity
        // In BFT consensus: need 2f+1 parents where f = (n-1)/3
        let f = (self.committee_size - 1) / 3;
        let min_parents = 2 * f + 1;
        
        // If we already have minimum or fewer parents, don't exclude any
        if total_parents <= min_parents {
            info!("Fissure attack: Not excluding any parents - already at minimum count ({} <= {})", 
                  total_parents, min_parents);
            return parents;
        }
        
        // Exclude as many victims as possible while maintaining 2f+1 quorum
        let max_excludable = total_parents - min_parents;
        
        let mut filtered_parents = Vec::new();
        let mut excluded_count = 0;
        let mut victim_count = 0;
        
        for parent_digest in parents {
            // Count victim blocks
            if self.is_victim_block(&parent_digest) {
                victim_count += 1;
            }
            
            // Only exclude if we haven't hit max excludable limit
            if excluded_count < max_excludable && self.should_exclude_parent(&parent_digest) {
                excluded_count += 1;
                info!("Fissure attack: Excluding victim parent {:?}", parent_digest);
                continue;
            }
            filtered_parents.push(parent_digest);
        }
        
        // Update attack metrics
        self.total_rounds += 1;
        self.successful_exclusions += excluded_count as u64;
        self.total_victim_blocks += victim_count as u64;
        
        let exclusion_rate = if victim_count > 0 { 
            (excluded_count as f64 / victim_count as f64) * 100.0 
        } else { 
            0.0 
        };
        
        let cumulative_asr = if self.total_victim_blocks > 0 {
            (self.successful_exclusions as f64 / self.total_victim_blocks as f64) * 100.0
        } else {
            0.0
        };
        
        info!("Fissure attack: Excluded {}/{} victim parents (max: {}) from {} total | Kept {} parents (min: {}) | Cumulative ASR: {:.1}%", 
              excluded_count, victim_count, max_excludable, total_parents, filtered_parents.len(), min_parents, cumulative_asr);
        
        filtered_parents
    }
    
    /// CORRECT FISSURE ATTACK: Filter victims by ACTUAL certificate origin
    /// Now that we have origins passed from aggregator, we can correctly identify victims
    fn preprocess_parents_with_origins(&mut self, parents_with_origins: Vec<(Digest, PublicKey)>) -> Vec<Digest> {
        let total_parents = parents_with_origins.len();
        
        // Calculate minimum required parents for consensus validity
        let f = (self.committee_size - 1) / 3;
        let min_parents = 2 * f + 1;
        
        if total_parents <= min_parents {
            info!("Fissure attack: Not excluding any parents - already at minimum count ({} <= {})", 
                  total_parents, min_parents);
            return parents_with_origins.into_iter().map(|(d, _)| d).collect();
        }
        
        // Exclude as many victims as possible while maintaining 2f+1 quorum
        let max_excludable = total_parents - min_parents;
        
        let mut filtered_parents = Vec::new();
        let mut excluded_count = 0;
        let mut victim_count = 0;
        
        for (parent_digest, origin) in parents_with_origins {
            // Check if origin is a victim node - now using ACTUAL origin!
            let is_victim = self.victim_nodes.contains(&origin);
            if is_victim {
                victim_count += 1;
            }
            
            // Calculate exclusion probability from paper
            let exclusion_prob = self.calculate_exclusion_probability();
            
            // Use deterministic pseudo-random based on digest
            let random_val = (parent_digest.as_ref()[0] as f64) / 255.0;
            
            // Exclude victim if: within limit AND probability check passes
            if is_victim && excluded_count < max_excludable && random_val < exclusion_prob {
                excluded_count += 1;
                info!("Fissure attack: Excluding victim parent {:?} from origin {}", parent_digest, origin);
                continue; // Skip this parent
            }
            
            filtered_parents.push(parent_digest);
        }
        
        // Update attack metrics
        self.total_rounds += 1;
        self.successful_exclusions += excluded_count as u64;
        self.total_victim_blocks += victim_count as u64;
        
        let cumulative_asr = if self.total_victim_blocks > 0 {
            (self.successful_exclusions as f64 / self.total_victim_blocks as f64) * 100.0
        } else {
            0.0
        };
        
        info!("Fissure attack (origin-based): Excluded {}/{} victims (max: {}) | Kept {} parents (min: {}) | Cumulative ASR: {:.1}%", 
              excluded_count, victim_count, max_excludable, filtered_parents.len(), min_parents, cumulative_asr);
        
        filtered_parents
    }

    /// Check if parent should be excluded based on fissure attack logic
    fn should_exclude_parent(&self, parent_digest: &Digest) -> bool {
        // Don't exclude anchor blocks (they're critical for consensus)
        if self.is_anchor_block(parent_digest) {
            return false;
        }

        // Check if this parent is from a victim node
        if self.is_victim_block(parent_digest) {
            // Apply probability-based exclusion using research equation
            let exclusion_prob = self.calculate_exclusion_probability();
            let random_factor = (parent_digest.as_ref()[0] as f64) / 255.0;
            
            if random_factor < exclusion_prob {
                return true; // Exclude this victim parent
            }
        }
        
        false
    }

    /// Check if block is an anchor block (should not be excluded)
    fn is_anchor_block(&self, block_digest: &Digest) -> bool {
        // Simple heuristic: anchor blocks have specific patterns
        // In practice, this would be more sophisticated
        let digest_bytes = block_digest.as_ref();
        digest_bytes[0] == 0 && digest_bytes[1] == 0
    }

    /// Check if block is from a victim node
    /// Uses hash-based probability to deterministically identify victim blocks
    fn is_victim_block(&self, block_digest: &Digest) -> bool {
        // Use digest bytes to probabilistically assign to nodes
        let digest_bytes = block_digest.as_ref();
        
        // Use multiple bytes for better distribution
        let hash_sum: u32 = digest_bytes.iter().take(8).map(|&b| b as u32).sum();
        let node_id = (hash_sum % self.committee_size as u32) as usize;
        
        // Victim nodes are the ones right after attackers
        // Check if this node_id falls in victim range
        let is_victim = self.victim_nodes.iter().any(|v| {
            let mut node_names: Vec<_> = self.attacker_nodes.iter().chain(self.victim_nodes.iter()).collect();
            // This fallback logic is complex, better to just use the HashSet
            false 
        }) || self.victim_nodes.len() > 0; // Simplified for now since we have origins
        
        // Actually, let's just use the HashSet if possible, but we only have block_digest here
        // If we don't have origin, we MUST use the hash-based heuristic
        let attacker_count = self.attacker_nodes.len();
        let victim_count = self.victim_nodes.len();
        let is_victim = node_id >= attacker_count && node_id < attacker_count + victim_count;
        
        if is_victim {
            debug!("Detected victim block from node {} (range {}-{}): {:?}", 
                   node_id, attacker_count, attacker_count + victim_count - 1, block_digest);
        }
        
        is_victim
    }

    fn calculate_exclusion_probability(&self) -> f64 {
        let fa = self.attacker_nodes.len() as f64;
        let fl = self.victim_nodes.len() as f64;
        let n = self.committee_size as f64; // Use actual committee size
        
        // Research equation: Pfis₀ = 1/2 + fa / (2.0 * (n - fl))
        let base_prob = 0.5 + fa / (2.0 * (n - fl));
        
        // Use standard network factor (1.0 = paper default)
        let nf: f64 = std::env::var("FISSURE_NETWORK_FACTOR")
            .unwrap_or_else(|_| "1.0".to_string())
            .parse()
            .unwrap_or(1.0);
        let adjusted_prob = base_prob * nf;

        // Apply decay factor for cumulative rounds (0.99 from guide)
        let decay_rate: f64 = std::env::var("FISSURE_DECAY_RATE")
            .unwrap_or_else(|_| "0.99".to_string())
            .parse()
            .unwrap_or(0.99);
        let decay_factor = decay_rate.powi(self.round as i32);
        
        // Final probability = base * network_factor * decay
        let final_prob = adjusted_prob * decay_factor;
        
        // Cap at reasonable probability matching paper's expectations
        final_prob.min(0.85)
    }

    async fn make_header(&mut self) {
        // PAPER'S METHODOLOGY: Pre-processing step before existing aggregator
        // This is the "lightweight modification" that adds attack logic
        
        // Get the parents with origins
        let original_parents_with_origins: Vec<(Digest, PublicKey)> = self.last_parents.drain(..).collect();
        
        // For fissure attack, exclude victims if possible. Speculative attack uses all parents.
        let processed_parents: Vec<Digest> = if self.attack_active && self.is_attacker && self.attack_mode == "fissure" {
            self.preprocess_parents_with_origins(original_parents_with_origins)
        } else {
            // Non-attack or Speculative: just extract digests
            original_parents_with_origins.into_iter().map(|(d, _)| d).collect()
        };

        // Make a new header with the processed parents
        let header = if self.attack_active && self.is_attacker && self.attack_mode == "speculative" {
            info!("SPECULATIVE ATTACK: Creating speculative header for node {}", self.name);
            let speculative_header = self.propose_speculative_block(processed_parents.into_iter().collect()).await;
            info!("SPECULATIVE ATTACK: Created speculative header: {:?}", speculative_header);
            speculative_header
        } else {
            info!("NORMAL HEADER: Creating normal header for node {}", self.name);
            Header::new(
                self.name,
                self.round,
                self.digests.drain(..).collect(),
                processed_parents.into_iter().collect(),
                &mut self.signature_service,
            )
            .await
        };
        debug!("Created {:?}", header);

        #[cfg(feature = "benchmark")]
        for digest in header.payload.keys() {
            // NOTE: This log entry is used to compute performance.
            info!("Created {} -> {:?}", header, digest);
        }

        // Send the new header to the `Core` that will broadcast and process it.
        info!("SENDING HEADER: Sending header {:?} to core for node {}", header, self.name);
        self.tx_core
            .send(header)
            .await
            .expect("Failed to send header");
        info!("HEADER SENT: Successfully sent header to core for node {}", self.name);
        
        // Mark as proposed for this round
        self.proposed_this_round = true;
        self.victim_observed_round = None;
        self.victim_observed_at = None;
    }

    // Main loop listening to incoming messages.
    pub async fn run(&mut self) {
        debug!("Dag starting at round {}", self.round);

        let timer = sleep(Duration::from_millis(self.max_header_delay));
        tokio::pin!(timer);

        loop {
            // Check if we can propose a new header. We propose a new header when one of the following
            // conditions is met:
            // 1. We have a quorum of certificates from the previous round and enough batches' digests;
            // 2. We have a quorum of certificates from the previous round and the specified maximum
            // inter-header delay has passed.
            let enough_parents = !self.last_parents.is_empty();
            let enough_digests = self.payload_size >= self.header_size;
            let timer_expired = timer.is_elapsed();
            // --- SLUGGISH ATTACK FIX ---
            // If in sluggish mode, we WANT to be late. 
            // We should ONLY propose if timer_expired, ignoring enough_digests.
            let is_sluggish = self.attack_active && self.is_attacker && self.attack_mode == "sluggish";
            let is_speculative = self.attack_active && self.is_attacker && self.attack_mode == "speculative";
            let speculative_victim_seen = is_speculative
                && self.victim_observed_round == Some(self.round);
            let victim_triggered = speculative_victim_seen
                && self.victim_observed_round == Some(self.round)
                && enough_parents
                && !self.digests.is_empty();
            let victim_grace_elapsed = self
                .victim_observed_at
                .map(|at| at.elapsed() >= Duration::from_millis(self.speculative_grace_ms))
                .unwrap_or(false);
            let victim_ready = victim_triggered
                && (
                    timer_expired
                    || (
                        victim_grace_elapsed
                            && enough_digests
                    )
                    || victim_grace_elapsed
                );
            
            let should_propose = if is_sluggish {
                timer_expired && enough_parents
            } else if is_speculative && self.speculative_require_victim {
                victim_ready
            } else if victim_ready {
                true
            } else {
                (timer_expired || enough_digests) && enough_parents
            };

            if should_propose {
                if is_sluggish {
                     info!("Sluggish attack: Node {} proposing after intentional delay of {}ms", self.name, self.max_header_delay);
                }
                // Make a new header.
                self.make_header().await;
                self.payload_size = 0;

                // Reschedule the timer.
                let deadline = Instant::now() + Duration::from_millis(self.max_header_delay);
                timer.as_mut().reset(deadline);
            }

            tokio::select! {
                Some((parents, round)) = self.rx_core.recv() => {
                    if is_speculative
                        && self.speculative_refresh_parents
                        && round + 1 == self.round
                        && !self.proposed_this_round
                        && parents.len() > self.last_parents.len()
                    {
                        info!(
                            "Speculative attack: refreshing parent set for round {} from {} to {} certificates",
                            self.round,
                            self.last_parents.len(),
                            parents.len()
                        );
                        self.last_parents = parents;
                        continue;
                    }

                    // Track the maximum round seen from cross-section of parents
                    // This helps sluggish attackers know how far behind they are
                    if round > self.honest_round {
                        self.honest_round = round;
                    }

                    if round < self.round {
                        continue;
                    }

                    // --- SLUGGISH ATTACK FIX: Force proposal before advancing if skipped ---
                    let is_sluggish = self.attack_active && self.is_attacker && self.attack_mode == "sluggish";
                    if is_sluggish {
                        // SLUGGISH ATTACK: Liveness-aware lagging
                        // Target: Stay exactly 1 round behind the honest majority
                        let lag = (self.honest_round as i64) - (self.round as i64);
                        if lag < 1 { // If we are not yet 1 round behind, delay to achieve it
                            info!("SLUGGISH ATTACK: Delaying proposal to lag round (Current: {}, Honest: {})", self.round, self.honest_round);
                            let delay = (self.max_header_delay as f64 * self.sluggish_timeout_multiplier) as u64;
                            sleep(Duration::from_millis(delay)).await;
                            info!("Sluggish Proposal Event: Node {} stayed in round {} (Honest was {})", self.name, self.round, self.honest_round);
                        } else {
                            debug!("SLUGGISH ATTACK: Already lagging enough (Round: {}, Honest: {}), proposing to maintain liveness", self.round, self.honest_round);
                        }
                    }

                    if is_sluggish && !self.proposed_this_round && !self.last_parents.is_empty() {
                        info!("Sluggish attack: Node {} forced proposal for round {} before advancing", self.name, self.round);
                        self.make_header().await;
                        self.payload_size = 0;
                    }

                    if is_speculative
                        && !self.proposed_this_round
                        && !self.last_parents.is_empty()
                        && !self.digests.is_empty()
                        && (!self.speculative_require_victim || speculative_victim_seen)
                    {
                        info!(
                            "Speculative attack: Node {} forced proposal for round {} before advancing with {} queued digests",
                            self.name,
                            self.round,
                            self.digests.len()
                        );
                        self.make_header().await;
                        self.payload_size = 0;
                    }

                    // Advance to the next round.
                    self.round = round + 1;
                    debug!("Dag moved to round {}", self.round);

                    // Signal that we have enough parent certificates to propose a new header.
                    self.last_parents = parents;
                    self.proposed_this_round = false;
                    self.victim_observed_round = None;
                    self.victim_observed_at = None;
                }
                Some((digest, worker_id)) = self.rx_workers.recv() => {
                    self.payload_size += digest.size();
                    self.digests.push((digest, worker_id));
                }
                Some(victim_round) = self.rx_victim_round.recv() => {
                    if self.attack_active && self.is_attacker && self.attack_mode == "speculative" {
                        self.victim_observed_round = Some(victim_round);
                        self.victim_observed_at = Some(Instant::now());
                        info!(
                            "Speculative attack: victim observed in round {}, arming proposal with {} queued digests and {} parents (grace {}ms)",
                            victim_round,
                            self.digests.len(),
                            self.last_parents.len(),
                            self.speculative_grace_ms
                        );
                    }
                }
                () = &mut timer => {
                    // Nothing to do.
                }
            }
        }
    }

    /// CORRECT SPECULATIVE ATTACK: Sample different worker transaction batches
    /// Generate up to p_max candidate blocks by varying transaction batches, choose largest digest
    async fn propose_speculative_block(&mut self, parents: Vec<Digest>) -> Header {
        use std::time::Instant;
        
        // Paper's parameters: p_max = 50
        let p_max_limit: usize = std::env::var("SPECULATIVE_P_MAX_LIMIT")
            .unwrap_or_else(|_| "50".to_string())
            .parse()
            .unwrap_or(50);
        let p_max = std::cmp::min(self.speculative_p_max, p_max_limit);
        
        let start_time = Instant::now();
        // SCALE FIX: Reduce default timeout from 100ms to 20ms for better quorum maintenance
        let timeout_ms: u64 = std::env::var("SPECULATIVE_TIMEOUT_MS")
            .unwrap_or_else(|_| "20".to_string())
            .parse()
            .unwrap_or(20);
        let timeout_duration = std::time::Duration::from_millis(timeout_ms);
        
        let mut best_digest: Option<Digest> = None;
        let mut best_candidate_digests: Option<Vec<(Digest, u32)>> = None;
        let mut best_parents: Option<std::collections::BTreeSet<Digest>> = None;
        
        info!(
            "Speculative attack: Generating {} candidate blocks with payload grinding (timeout: {}ms)",
            p_max,
            timeout_duration.as_millis()
        );
        
        // Get all available digests from workers
        let all_digests: Vec<(Digest, u32)> = self.digests.drain(..).collect();
        let fixed_parents: std::collections::BTreeSet<Digest> = parents.iter().cloned().collect();
        
        // Paper's methodology: Speculative attack chooses the largest digest among candidates.
        // We ensure we ALWAYS have at least a quorum of parents.
        for i in 0..p_max {
            // Check timeout
            if i > 0 && start_time.elapsed() > timeout_duration {
                debug!("Speculative attack: Timeout reached after {}ms at candidate {}", 
                      start_time.elapsed().as_millis(), i);
                break;
            }
            
            // 1. Sample combinations of worker batches (primary source of entropy)
            let candidate_digests = self.sample_worker_batches(&all_digests, i);
            
            // Paper-aligned speculative attack varies transaction-batch samples and
            // keeps the parent set fixed for the round.
            let candidate_parents = fixed_parents.clone();

            // 3. Add Nonce-based grinding (DIVERSITY ENHANCEMENT)
            // Even if payloads and parents are the same, we want unique digests.
            // Since we can't add a field to Header, we vary the "include/exclude" of batches 
            // more aggressively in sample_worker_batches using candidate_index.
            
            // Create a temporary header format to compute its digest
            let temp_payload: std::collections::BTreeMap<Digest, u32> = candidate_digests.iter().cloned().collect();
            
            // Compute the header digest
            let header_digest = self.compute_header_digest(&temp_payload, &candidate_parents);
            
            match &best_digest {
                None => {
                    best_digest = Some(header_digest.clone());
                    best_candidate_digests = Some(candidate_digests);
                    best_parents = Some(candidate_parents);
                },
                Some(current_best) => {
                    if self.digest_wins_over(&header_digest, current_best) {
                        best_digest = Some(header_digest.clone());
                        best_candidate_digests = Some(candidate_digests);
                        best_parents = Some(candidate_parents);
                    }
                }
            }
        }
        
        // Update metrics
        self.speculative_attempts += p_max as u64;
        
        let chosen_digests = best_candidate_digests.expect("Should have at least one candidate");
        let chosen_digest = best_digest.expect("Should have at least one candidate");
        let chosen_parents = best_parents.expect("Should have at least one candidate");
        
        info!(
            "Speculative attack: Chose optimized candidate with digest {:?} using {} parents from {} attempts in {}ms",
            chosen_digest, chosen_parents.len(), p_max, start_time.elapsed().as_millis()
        );
        
        // Create the final header with the best found combination
        let payload: std::collections::BTreeMap<Digest, u32> = chosen_digests.into_iter().collect();
        
        let final_header = Header::new(
            self.name,
            self.round,
            payload,
            chosen_parents,
            &mut self.signature_service,
        ).await;
        
        final_header
    }
    
    /// Sample different combinations of worker batches for speculative attack
    /// This implements the paper's methodology of sampling different transaction batches
    fn sample_worker_batches(&self, all_digests: &[(Digest, u32)], candidate_index: usize) -> Vec<(Digest, u32)> {
        // Derive an independent deterministic selector per worker so p_max=50
        // still explores combinations across all workers. The old mixed-radix
        // pattern only varied the first few workers when NUM_WORKERS was large.
        let mut sampled = Vec::new();
        let num_workers: usize = std::env::var("NUM_WORKERS")
            .unwrap_or_else(|_| "4".to_string())
            .parse()
            .unwrap_or(4);

        for worker_id in 0..num_workers {
            // Find digests from this worker
            let worker_digests: Vec<_> = all_digests
                .iter()
                .filter(|(_, wid)| *wid == worker_id as u32)
                .collect();
            
            if !worker_digests.is_empty() {
                let worker_seed = self.speculative_worker_seed(candidate_index, worker_id);
                let variant = (worker_seed % 6) as u8;
                let latest_window = usize::min(4, worker_digests.len());
                let recent_start = worker_digests.len().saturating_sub(latest_window);
                let recent_slice = &worker_digests[recent_start..];
                let alt_idx = recent_start + ((worker_seed as usize / 7) % latest_window);
                let alt_idx_2 = recent_start + ((worker_seed as usize / 17) % latest_window);
                
                match variant {
                    0 => {
                        // Include the latest batch only.
                        if let Some((digest, wid)) = worker_digests.last() {
                            sampled.push(((*digest).clone(), *wid));
                        }
                    },
                    1 => {
                        // Include a short recent window to exploit queued batches.
                        for (digest, wid) in recent_slice.iter().rev().take(2) {
                            sampled.push(((*digest).clone(), *wid));
                        }
                    },
                    2 => {
                        // Include a deterministic alternate batch, plus the latest one
                        // when they differ, to widen the candidate space.
                        if let Some((digest, wid)) = worker_digests.get(alt_idx) {
                            sampled.push(((*digest).clone(), *wid));
                        }
                        if let Some((digest, wid)) = worker_digests.last() {
                            sampled.push(((*digest).clone(), *wid));
                        }
                    },
                    3 => {
                        // Include the full recent window for this worker.
                        for (digest, wid) in recent_slice {
                            sampled.push(((*digest).clone(), *wid));
                        }
                    },
                    4 => {
                        // Include two deterministic alternates from the recent window.
                        if let Some((digest, wid)) = worker_digests.get(alt_idx) {
                            sampled.push(((*digest).clone(), *wid));
                        }
                        if let Some((digest, wid)) = worker_digests.get(alt_idx_2) {
                            sampled.push(((*digest).clone(), *wid));
                        }
                    },
                    _ => {
                        // Exclude this worker's batches for this candidate.
                    }
                }
            }
        }

        // Deduplicate while preserving the first-seen order.
        let mut unique = Vec::with_capacity(sampled.len());
        let mut seen = HashSet::with_capacity(sampled.len());
        for entry in sampled {
            if seen.insert(entry.0.clone()) {
                unique.push(entry);
            }
        }
        
        // If no worker batches available, use all available digests
        if unique.is_empty() {
            all_digests.to_vec()
        } else {
            unique
        }
    }

    fn speculative_worker_seed(&self, candidate_index: usize, worker_id: usize) -> u64 {
        // SplitMix64-style mixer to decorrelate per-worker candidate choices while
        // remaining deterministic for a given round and candidate index.
        let mut seed = (self.round as u64).wrapping_shl(32)
            ^ candidate_index as u64
            ^ ((worker_id as u64 + 1).wrapping_mul(0x9E37_79B9_7F4A_7C15));
        seed = (seed ^ (seed >> 30)).wrapping_mul(0xBF58_476D_1CE4_E5B9);
        seed = (seed ^ (seed >> 27)).wrapping_mul(0x94D0_49BB_1331_11EB);
        seed ^ (seed >> 31)
    }
    
    /// Compute header digest for speculative attack comparison
    /// This determines which candidate block has the best digest for ordering
    /// Compute certificate digest for speculative attack comparison
    /// CRITICAL: Matches Certificate::digest() which wraps the header
    /// This determines which candidate block has the best digest for ordering in Consensus
    fn compute_header_digest(&self, payload: &std::collections::BTreeMap<Digest, u32>, parents: &std::collections::BTreeSet<Digest>) -> Digest {
        use ed25519_dalek::Digest as _;
        use ed25519_dalek::Sha512;
        
        // 1. Compute Header Digest first (matches Header::digest)
        let mut header_hasher = Sha512::new();
        header_hasher.update(self.name.as_ref());
        header_hasher.update(&self.round.to_le_bytes());
        for (digest, worker_id) in payload {
            header_hasher.update(digest.as_ref());
            header_hasher.update(&worker_id.to_le_bytes());
        }
        for parent in parents {
            header_hasher.update(parent.as_ref());
        }
        let header_id_bytes = header_hasher.finalize();
        // Keep as full 64 bytes or truncate? checking messages.rs impl...
        // Header::digest truncates to 32 bytes
        let header_id = &header_id_bytes.as_slice()[..32];

        // 2. Compute Certificate Digest (matches Certificate::digest)
        // Consensus sorts by this value
        let mut cert_hasher = Sha512::new();
        cert_hasher.update(header_id);
        cert_hasher.update(&self.round.to_le_bytes());
        cert_hasher.update(self.name.as_ref());

        let cert_hash_bytes = cert_hasher.finalize();
        Digest(cert_hash_bytes.as_slice()[..32].try_into().unwrap())
    }
    
    /// Compare digests for LOP (Lexicographic Ordering Protocol) advantage
    /// Returns true if digest1 wins over digest2 in the ordering protocol
    fn digest_wins_over(&self, digest1: &Digest, digest2: &Digest) -> bool {
        // Enhanced LOP comparison for better speculative attack performance
        // The paper uses lexicographic ordering where larger digests win
        
        let bytes1 = digest1.as_ref();
        let bytes2 = digest2.as_ref();
        
        // Lexicographic comparison (byte by byte, larger wins)
        for (b1, b2) in bytes1.iter().zip(bytes2.iter()) {
            if *b1 > *b2 {
                return true;
            } else if *b1 < *b2 {
                return false;
            }
            // Continue if equal
        }
        
        // If all bytes are equal, digest1 wins (tie-breaker)
        true
    }
    
    /// Compute candidate digest using proper cryptographic hash
    /// Uses Sha512 (same as original Narwhal-Tusk) for hashing of header template + nonce
    fn compute_candidate_digest(&self, base_digests: &[(Digest, u32)], nonce: u64) -> Digest {
        use ed25519_dalek::Digest as _;
        use ed25519_dalek::Sha512;
        
        let mut hasher = Sha512::new();
        
        // Hash the base digests
        for (digest, worker_id) in base_digests {
            hasher.update(digest.as_ref());
            hasher.update(&worker_id.to_le_bytes());
        }
        
        // Hash the nonce
        hasher.update(&nonce.to_le_bytes());
        
        // Hash the round and proposer name for uniqueness
        hasher.update(&self.round.to_le_bytes());
        hasher.update(self.name.as_ref());
        
        // Get the final digest (same as original Narwhal-Tusk)
        let hash_bytes = hasher.finalize();
        Digest(hash_bytes.as_slice()[..32].try_into().unwrap())
    }
    
    /// Compute nonce digest for final header
    fn compute_nonce_digest(&self, nonce: u64) -> Digest {
        use ed25519_dalek::Digest as _;
        use ed25519_dalek::Sha512;
        
        let mut hasher = Sha512::new();
        hasher.update(&nonce.to_le_bytes());
        hasher.update(&self.round.to_le_bytes());
        hasher.update(self.name.as_ref());
        
        let hash_bytes = hasher.finalize();
        Digest(hash_bytes.as_slice()[..32].try_into().unwrap())
    }
    
    /// Generate deterministic but unpredictable nonce
    /// Uses Sha512 (same as original Narwhal-Tusk) to create a nonce based on round, proposer, and attempt
    fn generate_deterministic_nonce(&self, attempt: usize) -> u64 {
        use ed25519_dalek::Digest as _;
        use ed25519_dalek::Sha512;
        
        let mut hasher = Sha512::new();
        hasher.update(&self.round.to_le_bytes());
        hasher.update(self.name.as_ref());
        hasher.update(&attempt.to_le_bytes());
        hasher.update(b"speculative_nonce"); // Salt for unpredictability
        
        let hash_bytes = hasher.finalize();
        u64::from_le_bytes(hash_bytes.as_slice()[..8].try_into().unwrap())
    }
}
