// Copyright(C) Facebook, Inc. and its affiliates.
use crate::error::{DagError, DagResult};
use crate::messages::{Certificate, Header, Vote};
use config::{Committee, Stake};
use crypto::{PublicKey, Signature};
use std::collections::HashSet;

#[cfg(feature = "benchmark")]
use log::info;

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
pub struct CertificatesAggregator {
    weight: Stake,
    certificates: Vec<Certificate>,
    used: HashSet<PublicKey>,
    /// FISSURE_RATIONAL only: whether a quorum has already been emitted for this round.
    /// The proposer accumulates what the core sends (`last_parents.extend`), so after the
    /// first quorum every later certificate is an extra. Without this flag a victim
    /// certificate arriving after quorum would look like "quorum unreachable without it"
    /// and be referenced anyway, silently disabling the attack on that round.
    emitted_quorum: bool,
}

impl CertificatesAggregator {
    pub fn new() -> Self {
        Self {
            weight: 0,
            certificates: Vec::new(),
            used: HashSet::new(),
            emitted_quorum: false,
        }
    }

    pub fn append(
        &mut self,
        certificate: Certificate,
        committee: &Committee,
    ) -> DagResult<Option<Vec<Certificate>>> {
        let origin = certificate.origin();

        // Ensure it is the first time this authority votes.
        if !self.used.insert(origin) {
            return Ok(None);
        }

        self.certificates.push(certificate);
        self.weight += committee.stake(&origin);
        if self.weight >= committee.quorum_threshold() {
            // self.weight = 0; // Ensures quorum is only reached once.
            return Ok(Some(self.certificates.drain(..).collect()));
        }
        Ok(None)
    }

    pub fn fissure_attack_append(
        &mut self,
        certificate: Certificate,
        committee: &Committee,
        victim: PublicKey,
    ) -> DagResult<Option<Vec<Certificate>>> {
        let origin = certificate.origin();
        // MULTI_VICTIM=K (K>1): exclude the first K honest authorities (multi-victim
        // attack) instead of the single target victim. Default (unset or 1) keeps the
        // original single-victim exclusion, so the default path is byte-identical.
        let excluded = match std::env::var("MULTI_VICTIM").ok().and_then(|v| v.parse::<usize>().ok()) {
            Some(k) if k > 1 => committee
                .authorities
                .iter()
                .filter(|(_, a)| a.attack_type == 0)
                .map(|(name, _)| *name)
                .take(k)
                .any(|v| v == origin),
            _ => origin == victim,
        };
        // RATIONAL FISSURE (env FISSURE_RATIONAL=1).
        //
        // The upstream hook below drops the victim's certificate before it is ever counted,
        // so an attacker must reach quorum from the remaining n-1 authorities. Because every
        // attacker excludes the SAME victim, attackers depend on one another's certificates:
        // at n=13 the honest non-victim pool is 8 against a quorum of 9, so each attacker
        // needs at least one other attacker's certificate to advance at all. Attackers are
        // systematically slower than honest nodes (they wait on 9 of 12 rather than 9 of 13),
        // so they drift behind together, the available pool falls to 8, and they deadlock
        // permanently. We measured exactly this: attackers stop advancing at round 11 of ~300
        // and commit 8 blocks against every honest validator's ~294.
        //
        // A rational attacker would never halt itself: refusing to make progress is not an
        // attack, it is a self-inflicted crash, and it produces a committed order in which
        // the attacker is simply absent. Under FISSURE_RATIONAL we therefore accumulate every
        // certificate and omit the victim only when the parents that remain still satisfy the
        // quorum, falling back to including it when they do not. Omitting a parent one can
        // afford to omit is precisely the legitimate action (i) of the threat model; the
        // attack's intent (deny the victim support) is preserved on every round where it is
        // achievable, and abandoned only where the alternative is to stop proposing.
        let rational = std::env::var("FISSURE_RATIONAL")
            .map(|v| v != "0")
            .unwrap_or(false);
        if excluded && !rational {
            #[cfg(feature = "benchmark")]
            info!("This is the victim block, victim is {}", origin);
            return Ok(None)
        }
        // Ensure it is the first time this authority votes.
        if !self.used.insert(origin) {
            return Ok(None);
        }

        self.certificates.push(certificate);
        self.weight += committee.stake(&origin);
        if rational && self.weight >= committee.quorum_threshold() {
            let kept: Vec<Certificate> = self
                .certificates
                .iter()
                .filter(|c| c.origin() != victim)
                .cloned()
                .collect();
            // After the first quorum the proposer only extends what it already has, so every
            // later certificate is an extra: emit the non-victim ones and never re-admit the
            // victim on the "unreachable" path, which would otherwise fire whenever the
            // victim's certificate simply arrived late.
            if self.emitted_quorum {
                self.certificates.clear();
                return if kept.is_empty() { Ok(None) } else { Ok(Some(kept)) };
            }
            let kept_weight: Stake = kept.iter().map(|c| committee.stake(&c.origin())).sum();
            if kept_weight >= committee.quorum_threshold() {
                #[cfg(feature = "benchmark")]
                info!(
                    "FISSURE_RATIONAL excluded victim {} keeping {} parents",
                    victim,
                    kept.len()
                );
                self.emitted_quorum = true;
                self.certificates.clear();
                return Ok(Some(kept));
            }
            // Genuinely cannot form a quorum without the victim: include it rather than halt.
            #[cfg(feature = "benchmark")]
            info!(
                "FISSURE_RATIONAL kept victim {} (quorum unreachable without it)",
                victim
            );
            self.emitted_quorum = true;
            return Ok(Some(self.certificates.drain(..).collect()));
        }
        if self.weight >= committee.quorum_threshold() {
            // self.weight = 0; // Ensures quorum is only reached once.
            // COLLUSION (env COLLUDE=1): instead of referencing every certificate
            // that arrived before quorum, the colluding attacker set preferentially
            // links co-attackers (a tight attacker sub-DAG) and fills with the
            // minimum honest certificates needed to reach a VALID quorum. The victim
            // is still excluded (it never entered self.certificates). Choosing which
            // valid parents to include is a legitimate honest action, so this stays
            // inside the protocol invariant. Default path (COLLUDE unset) is unchanged.
            if std::env::var("COLLUDE").map(|v| v == "1").unwrap_or(false) {
                let parents = self.select_colluder_quorum(committee);
                #[cfg(feature = "benchmark")]
                info!("FairDag COLLUDE selected {} colluder-preferring parents", parents.len());
                self.certificates.clear();
                return Ok(Some(parents));
            }
            return Ok(Some(self.certificates.drain(..).collect()));
        }
        Ok(None)
    }

    /// Build a valid quorum from the accumulated (victim-excluded) certificates,
    /// preferring co-attacker certificates (authorities with attack_type != 0) and
    /// adding the minimum number of honest certificates required to reach quorum.
    fn select_colluder_quorum(&self, committee: &Committee) -> Vec<Certificate> {
        let colluders: HashSet<PublicKey> = committee
            .authorities
            .iter()
            .filter(|(_, authority)| authority.attack_type != 0)
            .map(|(name, _)| *name)
            .collect();
        let mut result: Vec<Certificate> = Vec::new();
        let mut weight: Stake = 0;
        // Co-attacker certificates first.
        for cert in self.certificates.iter() {
            if colluders.contains(&cert.origin()) {
                weight += committee.stake(&cert.origin());
                result.push(cert.clone());
            }
        }
        // Fill with the minimum honest certificates to reach a valid quorum.
        if weight < committee.quorum_threshold() {
            for cert in self.certificates.iter() {
                if !colluders.contains(&cert.origin()) {
                    weight += committee.stake(&cert.origin());
                    result.push(cert.clone());
                    if weight >= committee.quorum_threshold() {
                        break;
                    }
                }
            }
        }
        result
    }

    // maybe can do more things here
    pub fn speculative_attack_append(
        &mut self,
        certificate: Certificate,
        committee: &Committee,
    ) -> DagResult<Option<Vec<Certificate>>> {
        let origin = certificate.origin();

        // Ensure it is the first time this authority votes.
        if !self.used.insert(origin) {
            return Ok(None);
        }

        self.certificates.push(certificate);
        self.weight += committee.stake(&origin);
        if self.weight >= committee.quorum_threshold() {
            // self.weight = 0; // Ensures quorum is only reached once.
            return Ok(Some(self.certificates.drain(..).collect()));
        }
        Ok(None)
    }
}
