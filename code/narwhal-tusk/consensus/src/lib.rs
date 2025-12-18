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
}

impl Consensus {
    pub fn spawn(
        committee: Committee,
        gc_depth: Round,
        rx_primary: Receiver<Certificate>,
        tx_primary: Sender<Certificate>,
        tx_output: Sender<Certificate>,
    ) {
        tokio::spawn(async move {
            Self {
                committee: committee.clone(),
                gc_depth,
                rx_primary,
                tx_primary,
                tx_output,
                genesis: Certificate::genesis(&committee),
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

    /// Flatten the dag referenced by the input certificate. This is a classic depth-first search (pre-order):
    /// https://en.wikipedia.org/wiki/Tree_traversal#Pre-order
    fn order_dag(&self, leader: &Certificate, state: &State) -> Vec<Certificate> {
        debug!("Processing sub-dag of {:?}", leader);
        let mut ordered = Vec::new();
        let mut already_ordered = HashSet::new();

        let mut buffer = vec![leader];
        while let Some(x) = buffer.pop() {
            debug!("Sequencing {:?}", x);
            ordered.push(x.clone());
            for parent in &x.header.parents {
                let (digest, certificate) = match state
                    .dag
                    .get(&(x.round() - 1))
                    .map(|x| x.values().find(|(x, _)| x == parent))
                    .flatten()
                {
                    Some(x) => x,
                    None => continue, // We already ordered or GC up to here.
                };

                // We skip the certificate if we (1) already processed it or (2) we reached a round that we already
                // committed for this authority.
                let mut skip = already_ordered.contains(&digest);
                skip |= state
                    .last_committed
                    .get(&certificate.origin())
                    .map_or_else(|| false, |r| r == &certificate.round());
                if !skip {
                    buffer.push(certificate);
                    already_ordered.insert(digest);
                }
            }
        }

        // Ensure we do not commit garbage collected certificates.
        ordered.retain(|x| x.round() + self.gc_depth >= state.last_committed_round);

        // Ordering the output by round is not really necessary but it makes the commit sequence prettier.
        ordered.sort_by_key(|x| x.round());
        
        // ASR TRACKING: Track when attacker blocks are ordered before victim blocks
        self.track_asr(&ordered);
        
        ordered
    }
    
    /// ASR TRACKING: Track when attacker blocks are ordered before victim blocks
    fn track_asr(&self, ordered: &[Certificate]) {
        // Check if attack tracking is enabled
        let attack_mode = std::env::var("ATTACK_MODE").unwrap_or_default();
        if attack_mode != "speculative" && attack_mode != "fissure" && attack_mode != "sluggish" {
            return;
        }
        
        info!("ASR TRACKING: Processing {} ordered certificates", ordered.len());
        
        // Only calculate ASR when we have sufficient blocks for meaningful statistics
        if ordered.len() < 10 {
            info!("ASR TRACKING: Skipping ASR calculation - insufficient blocks ({})", ordered.len());
            return;
        }
        
        let attacker_ratio: f64 = std::env::var("ATTACKER_RATIO")
            .unwrap_or_else(|_| "0.3".to_string())
            .parse()
            .unwrap_or(0.3);
        let victim_ratio: f64 = std::env::var("VICTIM_RATIO")
            .unwrap_or_else(|_| "0.2".to_string())
            .parse()
            .unwrap_or(0.2);
        
        let committee_size = self.committee.size();
        let attacker_count = (committee_size as f64 * attacker_ratio) as usize;
        let victim_count = (committee_size as f64 * victim_ratio) as usize;
        
        info!("ASR TRACKING: Committee size: {}, Attacker count: {}, Victim count: {}", 
              committee_size, attacker_count, victim_count);
        
        // Identify attacker and victim nodes (use same logic as proposer)
        // CRITICAL FIX: Use the same committee structure as proposer
        let mut authority_keys: Vec<PublicKey> = self.committee
            .authorities
            .keys()
            .cloned()
            .collect();
        authority_keys.sort(); // Ensure consistent ordering (same as proposer)
        
        info!("ASR TRACKING: Authority keys (sorted): {:?}", authority_keys);
        info!("ASR TRACKING: First {} nodes as attackers: {:?}", attacker_count, &authority_keys[..attacker_count]);
        
        let attacker_nodes: HashSet<PublicKey> = authority_keys
            .iter()
            .take(attacker_count)
            .cloned()
            .collect();
            
        let victim_nodes: HashSet<PublicKey> = authority_keys
            .iter()
            .rev()
            .take(victim_count)
            .cloned()
            .collect();
        
        info!("ASR TRACKING: Authority keys (sorted): {:?}", authority_keys);
        info!("ASR TRACKING: First {} nodes as attackers: {:?}", attacker_count, attacker_nodes);
        info!("ASR TRACKING: Last {} nodes as victims: {:?}", victim_count, victim_nodes);
        
        // Track cross-round ordering (as per paper methodology)
        let mut attacker_blocks = Vec::new();
        let mut victim_blocks = Vec::new();
        
        info!("ASR TRACKING: Attacker nodes: {:?}", attacker_nodes);
        info!("ASR TRACKING: Victim nodes: {:?}", victim_nodes);
        
        // Find all attacker and victim blocks across all rounds
        for (position, block) in ordered.iter().enumerate() {
            let author = block.origin();
            let round = block.round();
            
            info!("ASR TRACKING: Block {} at position {} in round {} by author {:?}", 
                  block.digest(), position, round, author);
            
            if attacker_nodes.contains(&author) {
                attacker_blocks.push((position, block, round));
                info!("ASR TRACKING: ✓ ATTACKER BLOCK {} at position {} in round {}", 
                      block.digest(), position, round);
            } else if victim_nodes.contains(&author) {
                victim_blocks.push((position, block, round));
                info!("ASR TRACKING: ✗ VICTIM BLOCK {} at position {} in round {}", 
                      block.digest(), position, round);
            } else {
                info!("ASR TRACKING: ○ HONEST BLOCK {} at position {} in round {} (author not attacker or victim)", 
                      block.digest(), position, round);
            }
        }
        
        info!("ASR TRACKING: Found {} attacker blocks and {} victim blocks across all rounds", 
              attacker_blocks.len(), victim_blocks.len());
        
        // CORRECT ASR CALCULATION: For each attacker block, check if it's ordered before ANY victim block
        // This gives the true attack success rate, not a cartesian product
        let mut successful_attacks = 0;
        let total_attacker_blocks = attacker_blocks.len();
        
        for (attacker_pos, attacker_block, attacker_round) in &attacker_blocks {
            let mut attacker_wins_against_any_victim = false;
            
            // Check if this attacker block is ordered before any victim block
            for (victim_pos, victim_block, victim_round) in &victim_blocks {
                let attacker_wins = if attacker_round == victim_round {
                    // Same round: compare positions
                    attacker_pos < victim_pos
                } else {
                    // Different rounds: earlier round wins
                    attacker_round < victim_round
                };
                
                if attacker_wins {
                    attacker_wins_against_any_victim = true;
                    info!(
                        "ASR SUCCESS: Attacker block {} (pos {}, round {}) ordered before victim block {} (pos {}, round {})",
                        attacker_block.digest(), attacker_pos, attacker_round, 
                        victim_block.digest(), victim_pos, victim_round
                    );
                    break; // Found at least one victim it beats, that's enough
                }
            }
            
            if attacker_wins_against_any_victim {
                successful_attacks += 1;
            } else {
                info!(
                    "ASR FAILURE: Attacker block {} (pos {}, round {}) not ordered before any victim block",
                    attacker_block.digest(), attacker_pos, attacker_round
                );
            }
        }
        
        // Calculate overall ASR (corrected formula)
        if total_attacker_blocks > 0 {
            let overall_asr = (successful_attacks as f64 / total_attacker_blocks as f64) * 100.0;
            info!(
                "ASR CALCULATION: Overall - {}/{} successful attacks = {:.1}% ASR",
                successful_attacks, total_attacker_blocks, overall_asr
            );
        } else {
            info!("ASR CALCULATION: No attacker blocks found - no attack attempts");
        }
    }
}
