// Copyright (c) Mysten Labs, Inc.
// SPDX-License-Identifier: Apache-2.0

use std::collections::HashSet;

use fastcrypto::hash::{Blake2b256, HashFunction};
use mysten_metrics::monitored_scope;
use sui_protocol_config::ConsensusTransactionOrdering;
use sui_types::{
    digests::TransactionDigest,
    executable_transaction::VerifiedExecutableTransactionWithAliases,
    transaction::TransactionDataAPI as _,
};

pub struct PostConsensusTxReorder {}

impl PostConsensusTxReorder {
    pub fn reorder(
        transactions: &mut [VerifiedExecutableTransactionWithAliases],
        kind: ConsensusTransactionOrdering,
    ) {
        Self::reorder_with_seed(transactions, kind, &[], &HashSet::new())
    }

    /// Same as `reorder`, with the commit digest as a tiebreak seed and the set of transactions
    /// that were deferred from an earlier commit. Deferred transactions keep their priority over
    /// new transactions at the same gas price (the invariant the stable sort used to provide); the
    /// seeded hash only orders transactions within one (gas price, deferred?) tier.
    pub fn reorder_with_seed(
        transactions: &mut [VerifiedExecutableTransactionWithAliases],
        kind: ConsensusTransactionOrdering,
        seed: &[u8],
        deferred: &HashSet<TransactionDigest>,
    ) {
        match kind {
            ConsensusTransactionOrdering::ByGasPrice => {
                if seeded_tiebreak_enabled() {
                    Self::order_by_gas_price_seeded(transactions, seed, deferred)
                } else {
                    Self::order_by_gas_price(transactions)
                }
            }
            ConsensusTransactionOrdering::None => (),
        }
    }

    fn order_by_gas_price(transactions: &mut [VerifiedExecutableTransactionWithAliases]) {
        let _scope = monitored_scope("ConsensusCommitHandler::order_by_gas_price");
        transactions.sort_by_key(|tx| {
            // Reverse order, so that transactions with higher gas price are put to the beginning.
            std::cmp::Reverse(tx.tx().transaction_data().gas_price())
        });
    }

    /// Research prototype of the proposed fix (env-gated; the default path above is unchanged).
    /// The sort key is (gas price desc, deferred-first, hash(commit digest || transaction digest)).
    /// Higher gas price still goes first, and transactions deferred from an earlier commit still
    /// keep their place ahead of new transactions at the same price, so congestion control is
    /// unaffected. Only transactions in the same (gas price, deferred?) tier, which the protocol
    /// previously ordered by the proposing validator's index, are now ordered by the hash. The key
    /// is identical on every validator, so execution stays deterministic, and a sender cannot
    /// predict it when signing because the commit digest does not yet exist. A production version
    /// would be a new `ConsensusTransactionOrdering` variant gated by a protocol version.
    fn order_by_gas_price_seeded(
        transactions: &mut [VerifiedExecutableTransactionWithAliases],
        seed: &[u8],
        deferred: &HashSet<TransactionDigest>,
    ) {
        let _scope = monitored_scope("ConsensusCommitHandler::order_by_gas_price_seeded");
        transactions.sort_by_cached_key(|tx| {
            let mut h = Blake2b256::default();
            h.update(seed);
            h.update(tx.tx().digest().inner());
            (
                std::cmp::Reverse(tx.tx().transaction_data().gas_price()),
                // false < true, so deferred transactions (not-deferred = false) sort first.
                !deferred.contains(tx.tx().digest()),
                h.finalize().digest,
            )
        });
    }
}

fn seeded_tiebreak_enabled() -> bool {
    std::env::var("SUI_SEEDED_TIEBREAK")
        .ok()
        .filter(|v| v != "0")
        .is_some()
}
