// Copyright(C) Facebook, Inc. and its affiliates.
use crate::aggregators::{CertificatesAggregator, VotesAggregator};
use crate::attacks::{
    Attacker, ATTACKING_INTERVAL, FISSURE_ATTACK, FISSURE_NOT_ACTIVE_ATTACK, MONITOR_NOTHING,
    SPECULATIVE_ATTACK, SPECULATIVE_NOT_DELEGATE_ATTACK, SLUGGISH_ATTACK, SLUGGISH_NOT_ACTIVE_ATTACK,
};
use crate::error::{DagError, DagResult};
use crate::messages::{Certificate, Header, Vote};
use crate::primary::{PrimaryMessage, Round};
use crate::synchronizer::Synchronizer;
use async_recursion::async_recursion;
use bytes::Bytes;
use config::Committee;
use crypto::Hash as _;
use crypto::{Digest, PublicKey, SignatureService};
use log::{debug, error, warn};
use network::{CancelHandler, ReliableSender};
use std::collections::{HashMap, HashSet};
use std::sync::atomic::{AtomicU64, Ordering};
use std::sync::Arc;
use store::Store;
use tokio::sync::mpsc::{Receiver, Sender};

#[cfg(test)]
#[path = "tests/core_tests.rs"]
pub mod core_tests;

pub struct Core {
    /// The public key of this primary.
    name: PublicKey,
    /// The committee information.
    committee: Committee,
    /// The persistent storage.
    store: Store,
    /// Handles synchronization with other nodes and our workers.
    synchronizer: Synchronizer,
    /// Service to sign headers.
    signature_service: SignatureService,
    /// The current consensus round (used for cleanup).
    consensus_round: Arc<AtomicU64>,
    /// The depth of the garbage collector.
    gc_depth: Round,

    /// Receiver for dag messages (headers, votes, certificates).
    rx_primaries: Receiver<PrimaryMessage>,
    /// Receives loopback headers from the `HeaderWaiter`.
    rx_header_waiter: Receiver<Header>,
    /// Receives loopback certificates from the `CertificateWaiter`.
    rx_certificate_waiter: Receiver<Certificate>,
    /// Receives our newly created headers from the `Proposer`.
    rx_proposer: Receiver<Header>,
    /// Output all certificates to the consensus layer.
    tx_consensus: Sender<Certificate>,
    /// Send valid a quorum of certificates' ids to the `Proposer` (along with their round).
    tx_proposer: Sender<(Vec<Certificate>, Round)>,
    /// Send the monitored victim certificate to proposer
    tx_monitor_header: Sender<Header>,

    /// The last garbage collected round.
    gc_round: Round,
    /// The authors of the last voted headers.
    last_voted: HashMap<Round, HashSet<PublicKey>>,
    /// The set of headers we are currently processing.
    processing: HashMap<Round, HashSet<Digest>>,
    /// The last header we proposed (for which we are waiting votes).
    current_header: Header,
    /// Aggregates votes into a certificate.
    votes_aggregator: VotesAggregator,
    /// Aggregates certificates to use as parents for new headers.
    certificates_aggregators: HashMap<Round, Box<CertificatesAggregator>>,
    /// A network sender to send the batches to the other workers.
    network: ReliableSender,
    /// Keeps the cancel handlers of the messages we sent.
    cancel_handlers: HashMap<Round, Vec<CancelHandler>>,

    /// The parameters of attacker
    attacker: Attacker,
}

impl Core {
    #[allow(clippy::too_many_arguments)]
    pub fn spawn(
        name: PublicKey,
        committee: Committee,
        store: Store,
        synchronizer: Synchronizer,
        signature_service: SignatureService,
        consensus_round: Arc<AtomicU64>,
        gc_depth: Round,
        rx_primaries: Receiver<PrimaryMessage>,
        rx_header_waiter: Receiver<Header>,
        rx_certificate_waiter: Receiver<Certificate>,
        rx_proposer: Receiver<Header>,
        tx_consensus: Sender<Certificate>,
        tx_proposer: Sender<(Vec<Certificate>, Round)>,
        tx_monitor_header: Sender<Header>,
        attacker: Attacker,
    ) {
        tokio::spawn(async move {
            Self {
                name,
                committee,
                store,
                synchronizer,
                signature_service,
                consensus_round,
                gc_depth,
                rx_primaries,
                rx_header_waiter,
                rx_certificate_waiter,
                rx_proposer,
                tx_consensus,
                tx_proposer,
                tx_monitor_header,
                gc_round: 0,
                last_voted: HashMap::with_capacity(2 * gc_depth as usize),
                processing: HashMap::with_capacity(2 * gc_depth as usize),
                current_header: Header::default(),
                votes_aggregator: VotesAggregator::new(),
                certificates_aggregators: HashMap::with_capacity(2 * gc_depth as usize),
                network: ReliableSender::new(),
                cancel_handlers: HashMap::with_capacity(2 * gc_depth as usize),
                attacker: attacker,
            }
            .run()
            .await;
        });
    }

    async fn process_own_header(&mut self, header: Header) -> DagResult<()> {
        // Reset the votes aggregator.
        self.current_header = header.clone();
        self.votes_aggregator = VotesAggregator::new();

        // Broadcast the new header in a reliable manner.
        let addresses = self
            .committee
            .others_primaries(&self.name)
            .iter()
            .map(|(_, x)| x.primary_to_primary)
            .collect();
        let bytes = bincode::serialize(&PrimaryMessage::Header(header.clone()))
            .expect("Failed to serialize our own header");
        let handlers = self.network.broadcast(addresses, Bytes::from(bytes)).await;
        self.cancel_handlers
            .entry(header.round)
            .or_insert_with(Vec::new)
            .extend(handlers);

        // Process the header.
        self.process_header(&header).await
    }

    #[async_recursion]
    async fn process_header(&mut self, header: &Header) -> DagResult<()> {
        debug!("Processing {:?}", header);
        // Indicate that we are processing this header.
        self.processing
            .entry(header.round)
            .or_insert_with(HashSet::new)
            .insert(header.id.clone());

        // Ensure we have the parents. If at least one parent is missing, the synchronizer returns an empty
        // vector; it will gather the missing parents (as well as all ancestors) from other nodes and then
        // reschedule processing of this header.
        let parents = self.synchronizer.get_parents(header).await?;
        if parents.is_empty() {
            debug!("Processing of {} suspended: missing parent(s)", header.id);
            return Ok(());
        }

        // Check the parent certificates. Ensure the parents form a quorum and are all from the previous round.
        let mut stake = 0;
        for x in parents {
            ensure!(
                x.round() + 1 == header.round,
                DagError::MalformedHeader(header.id.clone())
            );
            stake += self.committee.stake(&x.origin());
        }
        ensure!(
            stake >= self.committee.quorum_threshold(),
            DagError::HeaderRequiresQuorum(header.id.clone())
        );

        // Ensure we have the payload. If we don't, the synchronizer will ask our workers to get it, and then
        // reschedule processing of this header once we have it.
        if self.synchronizer.missing_payload(header).await? {
            debug!("Processing of {} suspended: missing payload", header);
            return Ok(());
        }

        // Store the header.
        let bytes = bincode::serialize(header).expect("Failed to serialize header");
        self.store.write(header.id.to_vec(), bytes).await;

        // jianting: recognize victim block (header), activate front-running attack
        if self.attacker.attack_type() == FISSURE_ATTACK
            || self.attacker.attack_type() == FISSURE_NOT_ACTIVE_ATTACK
        {
            if self.attacker.victims().contains(&header.author)
                && self.fissure_target_victim() == Some(header.author)
                && header.round % ATTACKING_INTERVAL == 0
            // && self.current_header.round + 1 <= header.round
            {
                self.tx_monitor_header
                    .send(header.clone())
                    .await
                    .expect("Failed to send victim header to proposer");
            }
        } else if self.attacker.attack_type() == SLUGGISH_ATTACK
            || self.attacker.attack_type() == SLUGGISH_NOT_ACTIVE_ATTACK
        {
            // TODO
            if self.attacker.victims().contains(&header.author)
                && self.attacker.is_target_victim(header.author)
                && header.round % ATTACKING_INTERVAL == 0
            {
                self.tx_monitor_header
                    .send(header.clone())
                    .await
                    .expect("Failed to send victim header to proposer");
            }
        } else if self.attacker.attack_type() == SPECULATIVE_ATTACK
            || self.attacker.attack_type() == SPECULATIVE_NOT_DELEGATE_ATTACK
        {
            if self.attacker.victims().contains(&header.author)
                && self.attacker.is_target_victim(header.author)
                && header.round % ATTACKING_INTERVAL == 0
            {
                self.tx_monitor_header
                    .send(header.clone())
                    .await
                    .expect("Failed to send victim header to proposer");
            }
        } else if self.attacker.attack_type() == MONITOR_NOTHING {
            if self.attacker.victims().contains(&header.author)
                && self.attacker.is_target_victim(header.author)
                && header.round % ATTACKING_INTERVAL == 0
            {
                self.tx_monitor_header
                    .send(header.clone())
                    .await
                    .expect("Failed to send victim header to proposer");
            }
        }
        // CENSORSHIP (env CENSOR=k): the first k non-victim authorities decline to vote for
        // headers authored by a victim. Voting is not compulsory. A validator that has not
        // voted is indistinguishable from one that has not yet received the header, and the
        // protocol already tolerates validators that do not vote, so a censoring node stays
        // inside its legal options and the invariant holds: no honest node is asked to accept
        // anything it would normally reject, and no validity rule is touched. On a certified
        // DAG a header needs a quorum of votes before its certificate exists, which makes
        // declining to vote the only action in the legitimate set that can keep a victim's
        // block out of the committed order entirely rather than merely moving it later.
        // Default (unset or 0) leaves the path below byte-identical to upstream.
        // The target is victims()[0], matching this fork's own single-victim convention
        // (see is_target_victim). The censoring set is the first k authorities in committee
        // order other than the target, so it is well defined for any k up to n-1 and is
        // independent of how many authorities are configured as attackers: the point of the
        // sweep is the number of validators declining to vote, not how they were recruited.
        let censor_k = std::env::var("CENSOR")
            .ok()
            .and_then(|v| v.parse::<usize>().ok())
            .unwrap_or(0);
        if censor_k > 0 {
            if let Some(target) = self.attacker.victims().first().copied() {
                if header.author == target {
                    let censoring: Vec<PublicKey> = self
                        .committee
                        .authorities
                        .iter()
                        .map(|(name, _)| *name)
                        .filter(|n| *n != target)
                        .take(censor_k)
                        .collect();
                    if censoring.iter().any(|n| *n == self.name) {
                        #[cfg(feature = "benchmark")]
                        log::info!(
                            "CENSOR_VOTE_WITHHELD round {} target {}",
                            header.round, target
                        );
                        return Ok(());
                    }
                }
            }
        }

        // Check if we can vote for this header.
        if self
            .last_voted
            .entry(header.round)
            .or_insert_with(HashSet::new)
            .insert(header.author)
        {
            // Make a vote and send it to the header's creator.
            let vote = Vote::new(header, &self.name, &mut self.signature_service).await;
            debug!("Created {:?}", vote);
            if vote.origin == self.name {
                self.process_vote(vote)
                    .await
                    .expect("Failed to process our own vote");
            } else {
                let address = self
                    .committee
                    .primary(&header.author)
                    .expect("Author of valid header is not in the committee")
                    .primary_to_primary;
                let bytes = bincode::serialize(&PrimaryMessage::Vote(vote))
                    .expect("Failed to serialize our own vote");
                let handler = self.network.send(address, Bytes::from(bytes)).await;
                self.cancel_handlers
                    .entry(header.round)
                    .or_insert_with(Vec::new)
                    .push(handler);
            }
        }
        Ok(())
    }

    #[async_recursion]
    async fn process_vote(&mut self, vote: Vote) -> DagResult<()> {
        debug!("Processing {:?}", vote);

        // Add it to the votes' aggregator and try to make a new certificate.
        if let Some(certificate) =
            self.votes_aggregator
                .append(vote, &self.committee, &self.current_header)?
        {
            debug!("Assembled {:?}", certificate);

            // Broadcast the certificate.
            let addresses = self
                .committee
                .others_primaries(&self.name)
                .iter()
                .map(|(_, x)| x.primary_to_primary)
                .collect();
            let bytes = bincode::serialize(&PrimaryMessage::Certificate(certificate.clone()))
                .expect("Failed to serialize our own certificate");
            let handlers = self.network.broadcast(addresses, Bytes::from(bytes)).await;
            self.cancel_handlers
                .entry(certificate.round())
                .or_insert_with(Vec::new)
                .extend(handlers);

            // Process the new certificate.
            self.process_certificate(certificate)
                .await
                .expect("Failed to process valid certificate");
        }
        Ok(())
    }

    /// A3 RELATIONSHIP dimension. By default every attacker targets the same
    /// victim (`victims()[0]`), i.e. the attacker set is already *colluding*.
    /// With INDEPENDENT=1 each attacker instead targets a distinct victim
    /// (attacker at position j targets victims()[j % |victims|]), so the
    /// attackers act *uncoordinated* and each fights alone. Comparing the two
    /// isolates what coordination is actually worth. Default path unchanged.
    fn fissure_target_victim(&self) -> Option<PublicKey> {
        if std::env::var("INDEPENDENT").map(|v| v == "1").unwrap_or(false) {
            let victims: Vec<PublicKey> = self
                .committee
                .authorities
                .iter()
                .filter(|(_, a)| a.attack_type == 0)
                .map(|(name, _)| *name)
                .collect();
            let attackers: Vec<PublicKey> = self
                .committee
                .authorities
                .iter()
                .filter(|(_, a)| a.attack_type != 0)
                .map(|(name, _)| *name)
                .collect();
            if !victims.is_empty() {
                if let Some(pos) = attackers.iter().position(|a| *a == self.name) {
                    return Some(victims[pos % victims.len()]);
                }
            }
        }
        // A3 RELATIONSHIP, multi-group value. RIVAL_GROUPS=G partitions the attacker set
        // into G groups that each coordinate internally on their own victim, so the set is
        // neither fully colluding (all on victims()[0]) nor fully independent (one victim
        // each). Attacker at position j joins group j % G, and group g targets
        // victims()[g % |victims|]. This is the middle of the A3 dimension: it measures
        // whether rival groups interfere with one another, or whether each simply gets the
        // benefit its own size would buy.
        //
        // Only *which* victim an attacker targets changes; the exclusion mechanism and
        // every consensus rule are untouched. Default path unchanged when unset.
        if let Some(groups) = std::env::var("RIVAL_GROUPS")
            .ok()
            .and_then(|v| v.parse::<usize>().ok())
            .filter(|g| *g > 1)
        {
            let victims: Vec<PublicKey> = self
                .committee
                .authorities
                .iter()
                .filter(|(_, a)| a.attack_type == 0)
                .map(|(name, _)| *name)
                .collect();
            let attackers: Vec<PublicKey> = self
                .committee
                .authorities
                .iter()
                .filter(|(_, a)| a.attack_type != 0)
                .map(|(name, _)| *name)
                .collect();
            if !victims.is_empty() {
                if let Some(pos) = attackers.iter().position(|a| *a == self.name) {
                    let group = pos % groups;
                    return Some(victims[group % victims.len()]);
                }
            }
        }
        self.attacker.target_victim()
    }

    #[async_recursion]
    async fn process_certificate(&mut self, certificate: Certificate) -> DagResult<()> {
        debug!("Processing {:?}", certificate);

        // Process the header embedded in the certificate if we haven't already voted for it (if we already
        // voted, it means we already processed it). Since this header got certified, we are sure that all
        // the data it refers to (ie. its payload and its parents) are available. We can thus continue the
        // processing of the certificate even if we don't have them in store right now.
        if !self
            .processing
            .get(&certificate.header.round)
            .map_or_else(|| false, |x| x.contains(&certificate.header.id))
        {
            // This function may still throw an error if the storage fails.
            self.process_header(&certificate.header).await?;
        }

        // Ensure we have all the ancestors of this certificate yet. If we don't, the synchronizer will gather
        // them and trigger re-processing of this certificate.
        if !self.synchronizer.deliver_certificate(&certificate).await? {
            debug!(
                "Processing of {:?} suspended: missing ancestors",
                certificate
            );
            return Ok(());
        }

        // Store the certificate.
        let bytes = bincode::serialize(&certificate).expect("Failed to serialize certificate");
        self.store.write(certificate.digest().to_vec(), bytes).await;

        // Check if we have enough certificates to enter a new dag round and propose a header.
        if self.attacker.attack_type() == FISSURE_ATTACK
            || self.attacker.attack_type() == FISSURE_NOT_ACTIVE_ATTACK
        {
            // Fissure front-running attack: don't link the victim block
            if let Some(target_victim) = self.fissure_target_victim() {
                if let Some(parents) = self
                    .certificates_aggregators
                    .entry(certificate.round())
                    .or_insert_with(|| Box::new(CertificatesAggregator::new()))
                    .fissure_attack_append(certificate.clone(), &self.committee, target_victim)?
                {
                    // Send it to the `Proposer`.
                    self.tx_proposer
                        .send((parents, certificate.round()))
                        .await
                        .expect("Failed to send certificate");
                }
            } else {
                error!("Can not find the victim node");
                panic!("Attack failure: no fissure attacker.");
            }
        } else if self.attacker.attack_type() == SLUGGISH_ATTACK
            || self.attacker.attack_type() == SLUGGISH_NOT_ACTIVE_ATTACK
        {
            // Sluggish front-running attack: slow down the creation of new blocks
            // TODO
            if let Some(parents) = self
                .certificates_aggregators
                .entry(certificate.round())
                .or_insert_with(|| Box::new(CertificatesAggregator::new()))
                .append(certificate.clone(), &self.committee)?
            {
                // Send it to the `Proposer`.
                self.tx_proposer
                    .send((parents, certificate.round()))
                    .await
                    .expect("Failed to send certificate");
            }
        } else if self.attacker.attack_type() == SPECULATIVE_ATTACK
            || self.attacker.attack_type() == SPECULATIVE_NOT_DELEGATE_ATTACK
        {
            // if let Some(speculative_delegate) = self.attacker.delegate_speculative() {
                if let Some(parents) = self
                    .certificates_aggregators
                    .entry(certificate.round())
                    .or_insert_with(|| Box::new(CertificatesAggregator::new()))
                    .speculative_attack_append(certificate.clone(), &self.committee)?
                {
                    // Send it to the `Proposer`.
                    self.tx_proposer
                        .send((parents, certificate.round()))
                        .await
                        .expect("Failed to send certificate");
                }
            // } else {
            //     error!("Can not find speculative delegate");
            //     panic!("Attack failure: no speculative attacker.");
            // }
        } else {
            // BRIBERY (env BRIBED=B): the B honest nodes immediately after the victim
            // accept an out-of-band offer to omit the victim's block from their own
            // parent set. Choosing which valid certificates to reference as parents is
            // a legitimate honest action, so a bribed node stays within its legal
            // options and the invariant holds. Default (unset/0) = normal append path.
            let bribed_count = std::env::var("BRIBED")
                .ok()
                .and_then(|v| v.parse::<usize>().ok())
                .unwrap_or(0);
            let is_bribed = bribed_count > 0 && {
                let honest: Vec<PublicKey> = self
                    .committee
                    .authorities
                    .iter()
                    .filter(|(_, a)| a.attack_type == 0)
                    .map(|(name, _)| *name)
                    .collect();
                honest.iter().skip(1).take(bribed_count).any(|n| *n == self.name)
            };
            let victim_opt = self.attacker.target_victim();
            let result = if is_bribed {
                match victim_opt {
                    Some(victim) => self
                        .certificates_aggregators
                        .entry(certificate.round())
                        .or_insert_with(|| Box::new(CertificatesAggregator::new()))
                        .fissure_attack_append(certificate.clone(), &self.committee, victim)?,
                    None => self
                        .certificates_aggregators
                        .entry(certificate.round())
                        .or_insert_with(|| Box::new(CertificatesAggregator::new()))
                        .append(certificate.clone(), &self.committee)?,
                }
            } else {
                self.certificates_aggregators
                    .entry(certificate.round())
                    .or_insert_with(|| Box::new(CertificatesAggregator::new()))
                    .append(certificate.clone(), &self.committee)?
            };
            if let Some(parents) = result {
                // Send it to the `Proposer`.
                self.tx_proposer
                    .send((parents, certificate.round()))
                    .await
                    .expect("Failed to send certificate");
            }
        }

        // Send it to the consensus layer.
        let id = certificate.header.id.clone();
        if let Err(e) = self.tx_consensus.send(certificate).await {
            warn!(
                "Failed to deliver certificate {} to the consensus: {}",
                id, e
            );
        }
        Ok(())
    }

    fn sanitize_header(&mut self, header: &Header) -> DagResult<()> {
        ensure!(
            self.gc_round <= header.round,
            DagError::TooOld(header.id.clone(), header.round)
        );

        // Verify the header's signature.
        header.verify(&self.committee)?;

        // TODO [issue #3]: Prevent bad nodes from sending junk headers with high round numbers.

        Ok(())
    }

    fn sanitize_vote(&mut self, vote: &Vote) -> DagResult<()> {
        ensure!(
            self.current_header.round <= vote.round,
            DagError::TooOld(vote.digest(), vote.round)
        );

        // Ensure we receive a vote on the expected header.
        ensure!(
            vote.id == self.current_header.id
                && vote.origin == self.current_header.author
                && vote.round == self.current_header.round,
            DagError::UnexpectedVote(vote.id.clone())
        );

        // Verify the vote.
        vote.verify(&self.committee).map_err(DagError::from)
    }

    fn sanitize_certificate(&mut self, certificate: &Certificate) -> DagResult<()> {
        ensure!(
            self.gc_round <= certificate.round(),
            DagError::TooOld(certificate.digest(), certificate.round())
        );

        // Verify the certificate (and the embedded header).
        certificate.verify(&self.committee).map_err(DagError::from)
    }

    // Main loop listening to incoming messages.
    pub async fn run(&mut self) {
        debug!(
            "The attacking type of the primary is {:?}",
            self.committee.attack_type(&self.name)
        );
        loop {
            let result = tokio::select! {
                // We receive here messages from other primaries.
                Some(message) = self.rx_primaries.recv() => {
                    match message {
                        PrimaryMessage::Header(header) => {
                            match self.sanitize_header(&header) {
                                Ok(()) => self.process_header(&header).await,
                                error => error
                            }

                        },
                        PrimaryMessage::Vote(vote) => {
                            match self.sanitize_vote(&vote) {
                                Ok(()) => self.process_vote(vote).await,
                                error => error
                            }
                        },
                        PrimaryMessage::Certificate(certificate) => {
                            match self.sanitize_certificate(&certificate) {
                                Ok(()) =>  self.process_certificate(certificate).await,
                                error => error
                            }
                        },
                        _ => panic!("Unexpected core message")
                    }
                },

                // We receive here loopback headers from the `HeaderWaiter`. Those are headers for which we interrupted
                // execution (we were missing some of their dependencies) and we are now ready to resume processing.
                Some(header) = self.rx_header_waiter.recv() => self.process_header(&header).await,

                // We receive here loopback certificates from the `CertificateWaiter`. Those are certificates for which
                // we interrupted execution (we were missing some of their ancestors) and we are now ready to resume
                // processing.
                Some(certificate) = self.rx_certificate_waiter.recv() => self.process_certificate(certificate).await,

                // We also receive here our new headers created by the `Proposer`.
                Some(header) = self.rx_proposer.recv() => self.process_own_header(header).await,
            };
            match result {
                Ok(()) => (),
                Err(DagError::StoreError(e)) => {
                    error!("{}", e);
                    panic!("Storage failure: killing node.");
                }
                Err(e @ DagError::TooOld(..)) => debug!("{}", e),
                Err(e) => warn!("{}", e),
            }

            // Cleanup internal state.
            let round = self.consensus_round.load(Ordering::Relaxed);
            if round > self.gc_depth {
                let gc_round = round - self.gc_depth;
                self.last_voted.retain(|k, _| k >= &gc_round);
                self.processing.retain(|k, _| k >= &gc_round);
                self.certificates_aggregators.retain(|k, _| k >= &gc_round);
                self.cancel_handlers.retain(|k, _| k >= &gc_round);
                self.gc_round = gc_round;
            }
        }
    }
}
