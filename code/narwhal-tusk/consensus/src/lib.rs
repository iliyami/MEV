// Copyright(C) Facebook, Inc. and its affiliates.
use config::{Committee, Stake};
use crypto::Hash as _;
use crypto::{Digest, PublicKey};
use log::{debug, info, log_enabled, warn};
use primary::{Certificate, Round};
use std::cmp::max;
use std::collections::{HashMap, HashSet};
use tokio::sync::mpsc::{Receiver, Sender};

#[cfg(test)]
#[path = "tests/consensus_tests.rs"]
pub mod consensus_tests;

/// The representation of the DAG in memory.
type Dag = HashMap<Round, HashMap<PublicKey, (Digest, Certificate)>>;

/// The state that needs to be persisted for crash-recovery.
struct State {
    /// The last committed round.
    last_committed_round: Round,
    // Keeps the last committed round for each authority. This map is used to clean up the dag and
    // ensure we don't commit twice the same certificate.
    last_committed: HashMap<PublicKey, Round>,
    /// Keeps the latest committed certificate (and its parents) for every authority. Anything older
    /// must be regularly cleaned up through the function `update`.
    dag: Dag,
}

impl State {
    fn new(genesis: Vec<Certificate>) -> Self {
        let genesis = genesis
            .into_iter()
            .map(|x| (x.origin(), (x.digest(), x)))
            .collect::<HashMap<_, _>>();

        Self {
            last_committed_round: 0,
            last_committed: genesis.iter().map(|(x, (_, y))| (*x, y.round())).collect(),
            dag: [(0, genesis)].iter().cloned().collect(),
        }
    }

    /// Update and clean up internal state base on committed certificates.
    fn update(&mut self, certificate: &Certificate, gc_depth: Round) {
        self.last_committed
            .entry(certificate.origin())
            .and_modify(|r| *r = max(*r, certificate.round()))
            .or_insert_with(|| certificate.round());

        let last_committed_round = *self.last_committed.values().max().unwrap();
        self.last_committed_round = last_committed_round;

        for (name, round) in &self.last_committed {
            self.dag.retain(|r, authorities| {
                authorities.retain(|n, _| n != name || r >= round);
                !authorities.is_empty() && r + gc_depth >= last_committed_round
            });
        }
    }
}

pub struct Consensus {
    /// The committee information.
    committee: Committee,
    /// The depth of the garbage collector.
    gc_depth: Round,

    /// Receives new certificates from the primary. The primary should send us new certificates only
    /// if it already sent us its whole history.
    rx_primary: Receiver<Certificate>,
    /// Outputs the sequence of ordered certificates to the primary (for cleanup and feedback).
    tx_primary: Sender<Certificate>,
    /// Outputs the sequence of ordered certificates to the application layer.
    tx_output: Sender<Certificate>,

    /// The genesis certificates.
    genesis: Vec<Certificate>,
    
    /// ASR TRACKING: Global finalization sequence for paper-aligned ASR measurement
    /// Each entry is (global_height, round, author)
    global_finalization: Vec<(usize, Round, PublicKey)>,
    
    /// FISSURE ATTACK: Attack configuration
    attack_active: bool,
    attack_mode: String,
    attacker_nodes: HashSet<PublicKey>,
    victim_nodes: HashSet<PublicKey>,
}

impl Consensus {
    fn resolve_victim_count(committee_size: usize, attacker_count: usize, victim_ratio: f64) -> usize {
        std::env::var("VICTIM_COUNT")
            .ok()
            .and_then(|value| value.parse::<usize>().ok())
            .unwrap_or_else(|| (committee_size as f64 * victim_ratio) as usize)
            .min(committee_size.saturating_sub(attacker_count))
    }

    pub fn spawn(
        committee: Committee,
        gc_depth: Round,
        rx_primary: Receiver<Certificate>,
        tx_primary: Sender<Certificate>,
        tx_output: Sender<Certificate>,
    ) {
        // FISSURE ATTACK: Initialize attack configuration
        let attack_mode = std::env::var("ATTACK_MODE").unwrap_or_default();
        let attack_active = attack_mode == "fissure" || attack_mode == "speculative" || attack_mode == "sluggish";
        
        let (attacker_nodes, victim_nodes) = if attack_active {
            let attacker_ratio: f64 = std::env::var("ATTACKER_RATIO")
                .unwrap_or_else(|_| "0.308".to_string())
                .parse()
                .unwrap_or(0.308);
            let victim_ratio: f64 = std::env::var("VICTIM_RATIO")
                .unwrap_or_else(|_| "0.231".to_string())
                .parse()
                .unwrap_or(0.231);
            
            let committee_size = committee.size();
            let attacker_count = (committee_size as f64 * attacker_ratio) as usize;
            let victim_count = Self::resolve_victim_count(committee_size, attacker_count, victim_ratio);
            
            let mut authority_keys: Vec<PublicKey> = committee.authorities.keys().cloned().collect();
            authority_keys.sort();
            
            // Attackers are first nodes
            let attackers: HashSet<PublicKey> = authority_keys
                .iter()
                .take(attacker_count)
                .cloned()
                .collect();
            
            // Victims are nodes after attackers
            let victims: HashSet<PublicKey> = authority_keys
                .iter()
                .skip(attacker_count)
                .take(victim_count)
                .cloned()
                .collect();
            
            if !victims.is_empty() {
                info!("CONSENSUS FISSURE ATTACK: Enabled with {} attacker nodes and {} victim nodes", attackers.len(), victims.len());
            }
            (attackers, victims)
        } else {
            (HashSet::new(), HashSet::new())
        };
        
        tokio::spawn(async move {
            Self {
                committee: committee.clone(),
                gc_depth,
                rx_primary,
                tx_primary,
                tx_output,
                genesis: Certificate::genesis(&committee),
                global_finalization: Vec::new(),
                attack_active,
                attack_mode,
                attacker_nodes,
                victim_nodes,
            }
            .run()
            .await;
        });
    }

    async fn run(&mut self) {
        // The consensus state (everything else is immutable).
        let mut state = State::new(self.genesis.clone());

        // Listen to incoming certificates.
        while let Some(certificate) = self.rx_primary.recv().await {
            debug!("Processing {:?}", certificate);
            let round = certificate.round();

            // Add the new certificate to the local storage.
            state
                .dag
                .entry(round)
                .or_insert_with(HashMap::new)
                .insert(certificate.origin(), (certificate.digest(), certificate));

            // Try to order the dag to commit. Start from the highest round for which we have at least
            // 2f+1 certificates. This is because we need them to reveal the common coin.
            let r = round - 1;

            // We only elect leaders for even round numbers.
            if r % 2 != 0 || r < 4 {
                continue;
            }

            // Get the certificate's digest of the leader of round r-2. If we already ordered this leader,
            // there is nothing to do.
            let leader_round = r - 2;
            if leader_round <= state.last_committed_round {
                continue;
            }
            let (leader_digest, leader) = match self.leader(leader_round, &state.dag) {
                Some(x) => x,
                None => continue,
            };

            // Check if the leader has f+1 support from its children (ie. round r-1).
            let stake: Stake = state
                .dag
                .get(&(r - 1))
                .expect("We should have the whole history by now")
                .values()
                .filter(|(_, x)| x.header.parents.contains(&leader_digest))
                .map(|(_, x)| self.committee.stake(&x.origin()))
                .sum();

            // If it is the case, we can commit the leader. But first, we need to recursively go back to
            // the last committed leader, and commit all preceding leaders in the right order. Committing
            // a leader block means committing all its dependencies.
            if stake < self.committee.validity_threshold() {
                debug!("Leader {:?} does not have enough support", leader);
                continue;
            }

            // Get an ordered list of past leaders that are linked to the current leader.
            debug!("Leader {:?} has enough support", leader);
            let mut sequence = Vec::new();
            for leader in self.order_leaders(leader, &state).iter().rev() {
                // Starting from the oldest leader, flatten the sub-dag referenced by the leader.
                for x in self.order_dag(leader, &state) {
                    // Update and clean up internal state.
                    state.update(&x, self.gc_depth);

                    // Add the certificate to the sequence.
                    sequence.push(x);
                }
            }

            // Log the latest committed round of every authority (for debug).
            if log_enabled!(log::Level::Debug) {
                for (name, round) in &state.last_committed {
                    debug!("Latest commit of {}: Round {}", name, round);
                }
            }

            // Output the sequence in the right order.
            for certificate in sequence {
                // ASR TRACKING: Record global finalization position
                let global_height = self.global_finalization.len();
                self.global_finalization.push((
                    global_height,
                    certificate.round(),
                    certificate.origin(),
                ));
                
                #[cfg(not(feature = "benchmark"))]
                info!("Committed {}", certificate.header);

                #[cfg(feature = "benchmark")]
                for digest in certificate.header.payload.keys() {
                    // NOTE: This log entry is used to compute performance.
                    info!("Committed {} -> {:?}", certificate.header, digest);
                }

                self.tx_primary
                    .send(certificate.clone())
                    .await
                    .expect("Failed to send certificate to primary");

                if let Err(e) = self.tx_output.send(certificate).await {
                    warn!("Failed to output certificate: {}", e);
                }
            }
            
            // ASR TRACKING: Calculate paper-aligned ASR on global finalization sequence
            self.calculate_global_asr();
        }
    }

    /// Returns the certificate (and the certificate's digest) originated by the leader of the
    /// specified round (if any).
    fn leader<'a>(&self, round: Round, dag: &'a Dag) -> Option<&'a (Digest, Certificate)> {
        // TODO: We should elect the leader of round r-2 using the common coin revealed at round r.
        // At this stage, we are guaranteed to have 2f+1 certificates from round r (which is enough to
        // compute the coin). We currently just use round-robin.
        #[cfg(test)]
        let coin = 0;
        #[cfg(not(test))]
        let coin = round;

        // Elect the leader.
        let mut keys: Vec<_> = self.committee.authorities.keys().cloned().collect();
        keys.sort();
        let leader = keys[coin as usize % self.committee.size()];

        // Return its certificate and the certificate's digest.
        dag.get(&round).map(|x| x.get(&leader)).flatten()
    }

    /// Order the past leaders that we didn't already commit.
    fn order_leaders(&self, leader: &Certificate, state: &State) -> Vec<Certificate> {
        let mut to_commit = vec![leader.clone()];
        let mut leader = leader;
        for r in (state.last_committed_round + 2..leader.round())
            .rev()
            .step_by(2)
        {
            // Get the certificate proposed by the previous leader.
            let (_, prev_leader) = match self.leader(r, &state.dag) {
                Some(x) => x,
                None => continue,
            };

            // Check whether there is a path between the last two leaders.
            if self.linked(leader, prev_leader, &state.dag) {
                to_commit.push(prev_leader.clone());
                leader = prev_leader;
            }
        }
        to_commit
    }

    /// Checks if there is a path between two leaders.
    fn linked(&self, leader: &Certificate, prev_leader: &Certificate, dag: &Dag) -> bool {
        let mut parents = vec![leader];
        for r in (prev_leader.round()..leader.round()).rev() {
            parents = dag
                .get(&(r))
                .expect("We should have the whole history by now")
                .values()
                .filter(|(digest, _)| parents.iter().any(|x| x.header.parents.contains(digest)))
                .map(|(_, certificate)| certificate)
                .collect();
        }
        parents.contains(&prev_leader)
    }

    fn order_dag(&self, leader: &Certificate, state: &State) -> Vec<Certificate> {
        debug!("Processing sub-dag of {:?}", leader);
        let mut ordered = Vec::new();
        let mut visited = HashSet::new();

        fn traverse(
            cert: &Certificate,
            state: &State,
            visited: &mut HashSet<Digest>,
            ordered: &mut Vec<Certificate>,
            attack_active: bool,
            attack_mode: &str,
            attacker_nodes: &HashSet<PublicKey>,
            victim_nodes: &HashSet<PublicKey>,
        ) {
            let digest = cert.digest();
            if visited.contains(&digest) {
                return;
            }

            // Skip if we reached a round that we already committed for this authority.
            if let Some(r) = state.last_committed.get(&cert.origin()) {
                if *r >= cert.round() {
                    return;
                }
            }

            // PAPER ALIGNMENT: Sort parents for deterministic traversal
            // Standard Bullshark tie-break: Sort by digest descending
            let mut parents: Vec<_> = cert.header.parents.iter().filter_map(|parent_digest| {
                state.dag.get(&(cert.round() - 1))
                    .and_then(|round_map| {
                        round_map.values().find(|(d, _)| d == parent_digest)
                    })
            }).collect();

            parents.sort_by(|(_, a), (_, b)| {
                b.digest().as_ref().cmp(a.digest().as_ref())
            });

            for (_, parent_cert) in parents {
                traverse(parent_cert, state, visited, ordered, attack_active, attack_mode, attacker_nodes, victim_nodes);
            }

            // Post-order: Add yourself AFTER your parents
            visited.insert(digest);
            ordered.push(cert.clone());
        }

        traverse(leader, state, &mut visited, &mut ordered, self.attack_active, &self.attack_mode, &self.attacker_nodes, &self.victim_nodes);

        // Ensure we do not commit garbage collected certificates.
        ordered.retain(|x| x.round() + self.gc_depth >= state.last_committed_round);

        // Restore explicit LOP sorting logic: round ascending, digest descending
        ordered.sort_by(|a, b| {
            a.round().cmp(&b.round()).then_with(|| {
                b.digest().as_ref().cmp(a.digest().as_ref())
            })
        });

        // ASR TRACKING: Track when attacker blocks are ordered before victim blocks
        self.track_asr(&ordered);
        
        ordered
    }
    
    /// ASR TRACKING: Track when attacker blocks are ordered before victim blocks
    /// PAPER-ALIGNED METHODOLOGY:
    /// - All-pairs matching (all attacker blocks × all victim blocks)
    /// - Filter: attacker_round >= victim_round (attacker creates block after witnessing victim)
    /// - Success: attacker_height < victim_height (attacker block ordered before victim block)
    /// - ASR = successes / total_pairs
    fn track_asr(&self, ordered: &[Certificate]) {
        // Check if attack tracking is enabled
        let attack_mode = std::env::var("ATTACK_MODE").unwrap_or_default();
        if attack_mode != "speculative" && attack_mode != "fissure" && attack_mode != "sluggish" {
            return;
        }
        
        info!("ASR TRACKING: Processing {} ordered certificates", ordered.len());
        
        let report_threshold: usize = std::env::var("ASR_REPORT_THRESHOLD")
            .unwrap_or_else(|_| "10".to_string())
            .parse()
            .unwrap_or(10);
            
        // Only calculate ASR when we have sufficient blocks for meaningful statistics
        if ordered.len() < report_threshold {
            return;
        }
        
        let attacker_ratio: f64 = std::env::var("ATTACKER_RATIO")
            .unwrap_or_else(|_| "0.33".to_string())
            .parse()
            .unwrap_or(0.33);
        let victim_ratio: f64 = std::env::var("VICTIM_RATIO")
            .unwrap_or_else(|_| "0.22".to_string())
            .parse()
            .unwrap_or(0.22);
        
        let committee_size = self.committee.size();
        let attacker_count = (committee_size as f64 * attacker_ratio) as usize;
        let victim_count = Self::resolve_victim_count(committee_size, attacker_count, victim_ratio);
        
        info!("ASR TRACKING: Committee size: {}, Attacker count: {}, Victim count: {}", 
              committee_size, attacker_count, victim_count);
        
        // Identify attacker and victim nodes (use same logic as proposer)
        let mut authority_keys: Vec<PublicKey> = self.committee
            .authorities
            .keys()
            .cloned()
            .collect();
        authority_keys.sort(); // Ensure consistent ordering (same as proposer)
        
        let attacker_nodes: HashSet<PublicKey> = authority_keys
            .iter()
            .take(attacker_count)
            .cloned()
            .collect();
            
        let victim_nodes: HashSet<PublicKey> = authority_keys
            .iter()
            .skip(attacker_count)
            .take(victim_count)
            .cloned()
            .collect();
        
        info!("ASR TRACKING: Attacker nodes: {:?}", attacker_nodes);
        info!("ASR TRACKING: Victim nodes: {:?}", victim_nodes);
        
        // Collect all attacker and victim blocks with (height/position, round)
        // Height = position in finalization sequence (index in ordered)
        let mut attacker_blocks: Vec<(usize, Round)> = Vec::new();
        let mut victim_blocks: Vec<(usize, Round)> = Vec::new();
        
        for (height, block) in ordered.iter().enumerate() {
            let author = block.origin();
            let round = block.round();
            
            if attacker_nodes.contains(&author) {
                attacker_blocks.push((height, round));
                info!("ASR TRACKING: ✓ ATTACKER BLOCK at height {} in round {}", height, round);
            } else if victim_nodes.contains(&author) {
                victim_blocks.push((height, round));
                info!("ASR TRACKING: ✗ VICTIM BLOCK at height {} in round {}", height, round);
            }
        }
        
        info!("ASR TRACKING: Found {} attacker blocks and {} victim blocks", 
              attacker_blocks.len(), victim_blocks.len());
        
        // PAPER-ALIGNED ASR CALCULATION: All-pairs matching
        // For each (attacker, victim) pair where attacker_round >= victim_round:
        //   Success if attacker_height < victim_height
        let mut successes = 0;
        let mut total_pairs = 0;
        
        for (att_height, att_round) in &attacker_blocks {
            for (vic_height, vic_round) in &victim_blocks {
                // FILTER: attacker creates block AFTER witnessing victim
                // This means attacker_round >= victim_round
                if *att_round >= *vic_round {
                    total_pairs += 1;
                    
                    // SUCCESS: attacker block height < victim block height
                    // (attacker block ordered before victim block in finalization)
                    if *att_height < *vic_height {
                        successes += 1;
                        info!(
                            "ASR SUCCESS: Attacker (height {}, round {}) ordered before Victim (height {}, round {})",
                            att_height, att_round, vic_height, vic_round
                        );
                    }
                }
            }
        }
        
        // Calculate ASR using paper formula
        if total_pairs > 0 {
            let asr = (successes as f64 / total_pairs as f64) * 100.0;
            info!(
                "ASR CALCULATION (Paper-Aligned): {}/{} successful pairs = {:.2}% ASR",
                successes, total_pairs, asr
            );
        } else {
            info!("ASR CALCULATION: No valid pairs found (either no blocks or all attacker blocks from earlier rounds)");
        }
    }
    
    /// GLOBAL ASR CALCULATION: Paper-aligned ASR on the entire finalization sequence
    /// This is the correct implementation per the research paper methodology:
    /// - ASR = (# attacker blocks with height < victim height) / (total valid pairs)
    /// - Valid pair: attacker_round >= victim_round (attacker sees victim before creating block)
    /// - Success: attacker_height < victim_height (attacker ordered before victim)
    fn calculate_global_asr(&self) {
        // Check if attack tracking is enabled
        let attack_mode = std::env::var("ATTACK_MODE").unwrap_or_default();
        if attack_mode != "speculative" && attack_mode != "fissure" && attack_mode != "sluggish" {
            return;
        }
        
        let authority_keys = self.committee.authorities.keys();
        let mut authority_keys: Vec<PublicKey> = authority_keys.cloned().collect();
        authority_keys.sort(); // Lexicographical sort
        
        let attacker_ratio: f64 = std::env::var("ATTACKER_RATIO")
            .unwrap_or_else(|_| "0.33".to_string())
            .parse()
            .unwrap_or(0.33);
        let victim_ratio: f64 = std::env::var("VICTIM_RATIO")
            .unwrap_or_else(|_| "0.22".to_string())
            .parse()
            .unwrap_or(0.22);
            
        let committee_size = self.committee.size();
        let attacker_count = (committee_size as f64 * attacker_ratio) as usize;
        let victim_count = Self::resolve_victim_count(committee_size, attacker_count, victim_ratio);
        
        let attacker_nodes: HashSet<PublicKey> = authority_keys
            .iter()
            .take(attacker_count)
            .cloned()
            .collect();
            
        let victim_nodes: HashSet<PublicKey> = authority_keys
            .iter()
            .skip(attacker_count)  // Skip attackers
            .take(victim_count)    // Take the next N as victims (same as proposer)
            .cloned()
            .collect();
        
        // Collect attacker and victim blocks from global finalization sequence
        // (global_height, round, author)
        let mut attacker_blocks: Vec<(usize, Round)> = Vec::new();
        let mut victim_blocks: Vec<(usize, Round)> = Vec::new();
        
        for (height, round, author) in &self.global_finalization {
            if attacker_nodes.contains(author) {
                attacker_blocks.push((*height, *round));
            } else if victim_nodes.contains(author) {
                victim_blocks.push((*height, *round));
            }
        }
        
        // PAPER-ALIGNED ASR CALCULATION
        // ASR-A: All-pairs within a small round window
        // ASR-B: Same-round pairs (direct competition)
        let mut successes_a = 0;
        let mut total_a = 0;
        let mut successes_b = 0;
        let mut total_b = 0;
        
        let window: i64 = std::env::var("ASR_ROUND_WINDOW")
            .unwrap_or_else(|_| "1".to_string()) // Default to 1 for more strict adjacency
            .parse()
            .unwrap_or(1);

        for (att_height, att_round) in &attacker_blocks {
            for (vic_height, vic_round) in &victim_blocks {
                let diff = (*vic_round as i64 - *att_round as i64);
                
                // Same-round ASR (ASR-B)
                if diff == 0 {
                    total_b += 1;
                    if *att_height < *vic_height {
                        successes_b += 1;
                    }
                }
                
                // Trans-round / All-pairs ASR (ASR-A)
                // Filter depends on attack mode
                let in_window = diff.abs() <= window;
                if in_window {
                    let eligible = if self.attack_mode == "sluggish" {
                        // Sluggish is a cross-round attack: the attacker wins by keeping
                        // its block in a strictly smaller round than the victim.
                        diff > 0 // att_round < vic_round
                    } else {
                        // Speculative/Fissure: Attacker is same or newer
                        diff <= 0 // att_round >= vic_round
                    };
                    
                    if eligible {
                        total_a += 1;
                        if *att_height < *vic_height {
                            successes_a += 1;
                        }
                    }
                }
            }
        }
        
        let log_frequency: usize = std::env::var("ASR_LOGGING_FREQUENCY")
            .unwrap_or_else(|_| "10".to_string())
            .parse()
            .unwrap_or(10);
            
        if self.global_finalization.len() % log_frequency == 0 {
            if total_a > 0 || total_b > 0 {
                let asr_a = if total_a > 0 { (successes_a as f64 / total_a as f64) * 100.0 } else { 0.0 };
                let asr_b = if total_b > 0 { (successes_b as f64 / total_b as f64) * 100.0 } else { 0.0 };
                
                info!(
                    "ASR REPORT ({}): ASR-A (All-Pairs): {:.2}% ({}/{}) | ASR-B (Same-Round): {:.2}% ({}/{}) | Blocks: {}",
                    self.attack_mode,
                    asr_a, successes_a, total_a,
                    asr_b, successes_b, total_b,
                    self.global_finalization.len()
                );
                // Print a marker for the test scripts to find
                info!("FINAL_ASR_RESULT: {:.2}%", asr_a);
            }
        }
    }
}
