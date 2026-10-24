use crate::{dag::DagUnit, MultiKeychain, UnitFinalizationHandler};

mod election;

/// Seeded ranking key for a round's election candidates (env ALEPH_HASH_SORT_SEED, 0 = upstream).
/// The key depends only on the seed and the candidate's own hash, so every node orders any two
/// candidates the same way, exactly as the upstream hash order does.
pub(crate) fn seeded_rank_key(seed: u64, bytes: &[u8]) -> u64 {
    use std::hash::{Hash, Hasher};
    let mut h = std::collections::hash_map::DefaultHasher::new();
    seed.hash(&mut h);
    bytes.hash(&mut h);
    h.finish()
}
mod extender;
mod units;

use extender::Extender;

/// A struct responsible for executing the Consensus protocol on a local copy of the Dag.
/// It receives units which are guaranteed to eventually appear in the Dags
/// of all honest nodes. The static Aleph Consensus algorithm is then run on this Dag in order
/// to finalize subsequent rounds of the Dag. More specifically whenever a new unit is received
/// this process checks whether a new round can be finalized and if so, it computes the batch of
/// units that should be finalized, and uses the finalization handler to report that to the user.
///
/// We refer to the documentation https://cardinal-cryptography.github.io/AlephBFT/internals.html
/// Section 5.4 for a discussion of this component.
pub struct Ordering<MK: MultiKeychain, UFH: UnitFinalizationHandler> {
    extender: Extender<DagUnit<UFH::Hasher, UFH::Data, MK>>,
    finalization_handler: UFH,
}

impl<MK: MultiKeychain, UFH: UnitFinalizationHandler> Ordering<MK, UFH> {
    pub fn new(finalization_handler: UFH) -> Self {
        let extender = Extender::new();
        Ordering {
            extender,
            finalization_handler,
        }
    }

    pub fn add_unit(&mut self, unit: DagUnit<UFH::Hasher, UFH::Data, MK>) {
        for batch in self.extender.add_unit(unit) {
            self.finalization_handler
                .batch_finalized(batch.into_iter().map(|unit| unit.into()).collect());
        }
    }
}
