// Copyright(C) Facebook, Inc. and its affiliates.
use crate::error::{DagError, DagResult};
use crate::messages::{Certificate, Header, Vote};
use config::{Committee, Stake};
use crypto::Hash as _;
use crypto::{Digest, PublicKey, Signature};
use std::collections::HashSet;
use std::env;
use log::{debug, info};

/// Aggregates votes for a particular header into a certificate.
pub struct VotesAggregator {
    weight: Stake,
    votes: Vec<(PublicKey, Signature)>,
    used: HashSet<PublicKey>,
}

impl VotesAggregator {
    pub fn new() -> Self {
        Self {
            weight: 0,
            votes: Vec::new(),
            used: HashSet::new(),
        }
    }

    pub fn append(
        &mut self,
        vote: Vote,
        committee: &Committee,
        header: &Header,
    ) -> DagResult<Option<Certificate>> {
        let author = vote.author;

        // Ensure it is the first time this authority votes.
        ensure!(self.used.insert(author), DagError::AuthorityReuse(author));

        self.votes.push((author, vote.signature));
        self.weight += committee.stake(&author);
        if self.weight >= committee.quorum_threshold() {
            self.weight = 0; // Ensures quorum is only reached once.
            return Ok(Some(Certificate {
                header: header.clone(),
                votes: self.votes.clone(),
            }));
        }
        Ok(None)
    }
}

/// Aggregate certificates and check if we reach a quorum.
/// ATTACK-AWARE: Supports fissure attack by filtering victim certificates
pub struct CertificatesAggregator {
    weight: Stake,
    certificates: Vec<(Digest, PublicKey)>, // Store digest AND origin
    used: HashSet<PublicKey>,
    // Attack configuration
    attack_active: bool,
    is_attacker: bool,
    victim_nodes: HashSet<PublicKey>,
    excluded_count: u64,
    total_victim_seen: u64,
}

impl CertificatesAggregator {
    pub fn new() -> Self {
        Self {
            weight: 0,
            certificates: Vec::new(),
            used: HashSet::new(),
            attack_active: false,
            is_attacker: false,
            victim_nodes: HashSet::new(),
            excluded_count: 0,
            total_victim_seen: 0,
        }
    }
    
    /// Create an attack-aware aggregator
    pub fn new_with_attack(is_attacker: bool, victim_nodes: HashSet<PublicKey>) -> Self {
        let attack_mode = env::var("ATTACK_MODE").unwrap_or_default();
        let attack_active = attack_mode == "fissure" || attack_mode == "speculative" || attack_mode == "sluggish";
        
        info!(
            "AGGREGATOR INIT: Creating attack-aware aggregator | is_attacker: {} | attack_active: {} | attack_mode: '{}' | victim_count: {}",
            is_attacker, attack_active, attack_mode, victim_nodes.len()
        );
        
        Self {
            weight: 0,
            certificates: Vec::new(),
            used: HashSet::new(),
            attack_active,
            is_attacker,
            victim_nodes,
            excluded_count: 0,
            total_victim_seen: 0,
        }
    }

    /// Returns (digests, origins) for passing to proposer
    pub fn append(
        &mut self,
        certificate: Certificate,
        committee: &Committee,
    ) -> DagResult<Option<Vec<(Digest, PublicKey)>>> {
        let origin = certificate.origin();

        // Ensure it is the first time this authority votes.
        if !self.used.insert(origin) {
            return Ok(None);
        }

        // ATTACK-AWARE: All certificates are added - Proposer will filter them
        // to maintain consensus safety (2f+1) while maximizing ASR
        self.certificates.push((certificate.digest(), origin));
        self.weight += committee.stake(&origin);

        if self.weight >= committee.quorum_threshold() {
            self.weight = 0; // Ensures quorum is only reached once.
            // Return digests WITH origins so proposer can do attack filtering
            return Ok(Some(self.certificates.drain(..).collect()));
        }
        Ok(None)
    }
    
    /// Calculate if we should exclude this victim certificate
    /// Uses paper's probability formula and ensures we maintain minimum parents
    fn should_exclude_victim(&self, committee: &Committee) -> bool {
        // Calculate minimum parents needed (2f+1 where f = (n-1)/3)
        let n = committee.size();
        let f = (n - 1) / 3;
        let min_parents = 2 * f + 1;
        
        // Calculate how many more certificates we expect to receive
        // Total possible = n, already received = certificates.len() + excluded_count + 1 (current)
        let total_processed = self.certificates.len() + self.excluded_count as usize + 1;
        let remaining_expected = if n > total_processed { n - total_processed } else { 0 };
        
        // Project: if we exclude this one, will we still have min_parents?
        // Current kept = certificates.len()
        // After excluding this = certificates.len() (unchanged)
        // Plus remaining = certificates.len() + remaining
        let projected_final = self.certificates.len() + remaining_expected;
        
        // If we can't afford to exclude, don't
        if projected_final < min_parents {
            return false;
        }
        
        // Also check: we shouldn't exclude more than (total - min_parents) victims
        let max_excludable = if n > min_parents { n - min_parents } else { 0 };
        if self.excluded_count >= max_excludable as u64 {
            return false;
        }
        
        // Apply paper's probability
        let attacker_ratio: f64 = env::var("ATTACKER_RATIO")
            .unwrap_or_else(|_| "0.33".to_string())
            .parse()
            .unwrap_or(0.33);
        let attacker_count = (n as f64 * attacker_ratio) as usize; 
        let victim_count = self.victim_nodes.len();
        
        // Paper's equation: Pfis₀ = 1/2 + fa / (2(n − fl))
        let fa = attacker_count as f64;
        let fl = victim_count as f64;
        let n_f = n as f64;
        
        let base_prob = 0.5 + fa / (2.0 * (n_f - fl));
        
        // Use deterministic pseudo-random based on excluded count
        let random_factor = ((self.excluded_count * 37 + self.total_victim_seen * 13) % 100) as f64 / 100.0;
        
        random_factor < base_prob
    }
}
