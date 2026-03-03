use crate::{units::Unit, Hasher, NodeCount, NodeIndex, NodeMap, Round};
use anyhow::Result;
use rand::Rng;
use std::env;
use thiserror::Error;

#[derive(Eq, Error, Debug, PartialEq)]
pub enum ConstraintError {
    #[error("Not enough parents.")]
    NotEnoughParents,
    #[error("Missing own parent.")]
    MissingOwnParent,
}

#[derive(Clone)]
pub struct UnitsCollector<H: Hasher> {
    candidates: NodeMap<(H::Hash, Round)>,
    for_round: Round,
    direct_parents: NodeCount,
}

impl<H: Hasher> UnitsCollector<H> {
    pub fn new_initial(n_members: NodeCount) -> Self {
        UnitsCollector {
            candidates: NodeMap::with_size(n_members),
            for_round: 1,
            direct_parents: NodeCount(0),
        }
    }

    pub fn from_previous(previous: &UnitsCollector<H>) -> Self {
        UnitsCollector {
            candidates: previous.candidates.clone(),
            for_round: previous.for_round + 1,
            direct_parents: NodeCount(0),
        }
    }

    pub fn add_unit<U: Unit<Hasher = H>>(&mut self, unit: &U) {
        let node_id = unit.creator();
        let hash = unit.hash();
        let round = unit.round();

        if round >= self.for_round {
            return;
        }

        let to_insert = match self.candidates.get(node_id) {
            None => Some((hash, round)),
            Some((_, r)) if *r < round => Some((hash, round)),
            _ => None,
        };

        if let Some(data) = to_insert {
            self.candidates.insert(node_id, data);
            if round == self.for_round - 1 {
                self.direct_parents += NodeCount(1);
            }
        }
    }

    pub fn prospective_parents(
        &self,
        node_id: NodeIndex,
    ) -> Result<&NodeMap<(H::Hash, Round)>, ConstraintError> {
        if self.direct_parents < self.candidates.size().consensus_threshold() {
            return Err(ConstraintError::NotEnoughParents);
        }
        match self.candidates.get(node_id) {
            Some((_, r)) if *r == self.for_round - 1 => Ok(&self.candidates),
            _ => Err(ConstraintError::MissingOwnParent),
        }
    }

    /// FISSURE ATTACK: Filtered parent selection that excludes victim nodes
    pub fn prospective_parents_filtered(
        &self,
        node_id: NodeIndex,
        attacker_id: NodeIndex,
    ) -> Result<NodeMap<(H::Hash, Round)>, ConstraintError> {
        // First check basic constraints
        if self.direct_parents < self.candidates.size().consensus_threshold() {
            return Err(ConstraintError::NotEnoughParents);
        }
        match self.candidates.get(node_id) {
            Some((_, r)) if *r == self.for_round - 1 => {},
            _ => return Err(ConstraintError::MissingOwnParent),
        }

        // Check if attack is active
        let attack_mode = env::var("ATTACK_MODE").unwrap_or_default();
        if attack_mode != "fissure" {
            // Return original candidates if attack not active
            return Ok(self.candidates.clone());
        }

        // Read attack configuration
        let attacker_ratio: f64 = env::var("ATTACKER_RATIO")
            .unwrap_or_else(|_| "0.308".to_string())
            .parse()
            .unwrap_or(0.308);
        let victim_ratio: f64 = env::var("VICTIM_RATIO")
            .unwrap_or_else(|_| "0.231".to_string())
            .parse()
            .unwrap_or(0.231);
        let n_members = self.candidates.size();
        // Use round() instead of ceil() to get exact count (3.003 -> 3, not 4)
        let n_attackers = ((n_members.0 as f64) * attacker_ratio).round() as usize;
        let n_victims = ((n_members.0 as f64) * victim_ratio).round() as usize;

        // Identify victim nodes (last n_victims nodes)
        // For 13 nodes with 0.231 ratio: 13 * 0.231 = 3.003 -> 3 victims (indices 10, 11, 12)
        let victim_start = n_members.0 - n_victims;
        let victim_indices: Vec<NodeIndex> = (victim_start..n_members.0)
            .map(|i| NodeIndex(i))
            .collect();

        // Check if current node is attacker
        if attacker_id.0 >= n_attackers {
            // Not an attacker, return original
            return Ok(self.candidates.clone());
        }

        // Log attack activation (only once per round to avoid spam)
        use log::debug;
        static mut LOGGED: bool = false;
        unsafe {
            if !LOGGED {
                debug!("FISSURE ATTACK: Active for attacker node {}, excluding victims {:?}", attacker_id.0, victim_indices);
                LOGGED = true;
            }
        }

        // Calculate base exclusion probability using paper's equation
        // Pfis₀ = 1/2 + fa / (2(n − fl))
        // where fa = number of attackers, fl = number of victims, n = total nodes
        let fa = n_attackers as f64;
        let fl = n_victims as f64;
        let n = n_members.0 as f64;
        let base_prob = 0.5 + fa / (2.0 * (n - fl));
        
        // MAXIMUM AGGRESSIVENESS for 80%+ ASR target
        // For 13 nodes: base_prob = 0.5 + 4/(2*(13-3)) = 0.5 + 0.2 = 0.7
        // Use very high network factor for maximum aggressiveness
        let network_factor = if n <= 13.0 {
            12.0  // Extremely aggressive for 13-node network
        } else {
            10.0  // Very strong for larger networks
        };
        let base_optimized_prob = (base_prob * network_factor).min(0.995);  // Cap at 99.5%
        
        // Determine parent round (round we're creating unit for - 1)
        let parent_round = self.for_round.saturating_sub(1);
        let quorum_threshold = n_members.consensus_threshold().0;

        // Count parents in parent round for quorum check
        let mut parent_round_count = 0;
        let mut parent_round_victims = 0;
        let mut parent_round_victim_indices = Vec::new();
        for (idx, &(_, round)) in self.candidates.iter() {
            if round == parent_round {
                parent_round_count += 1;
                if victim_indices.contains(&idx) {
                    parent_round_victims += 1;
                    parent_round_victim_indices.push(idx);
                }
            }
        }

        // FORCE-INCLUDE GATING (Backrun / Sandwich)
        let attack_type = env::var("ATTACK_TYPE").unwrap_or_else(|_| "frontrun".to_string());
        
        // REVERT: Removed protocol-violating blocking wait. 
        // Real nodes should never stall by returning NotEnoughParents if they actually have N-f parents.
        // Instead, we just adjust parent selection logic if needed, but here we keep it simple to verify true resilience.

        // Smart quorum calculation: Can we exclude ALL victims from parent round?
        // Quorum = attackers (4) + honest (6) = 10 > 9 (threshold) ✓
        // So we can safely exclude all victims from parent-round!
        let can_exclude_all_parent_round_victims = (parent_round_count - parent_round_victims) >= quorum_threshold;

        // Filter candidates, excluding victim nodes with optimized quorum-aware probability
        let mut filtered = NodeMap::with_size(n_members);
        let mut rng = rand::thread_rng();
        let mut excluded_parent_round_count = 0;
        let mut excluded_non_parent_round_count = 0;
        
        // First pass: Process non-parent-round victims (can exclude deterministically)
        // Second pass: Process parent-round victims (quorum-aware)
        
        for (idx, &(hash, round)) in self.candidates.iter() {
            // Always include own parent
            if idx == node_id {
                filtered.insert(idx, (hash, round));
                continue;
            }

            // Check if this is a victim node
            let is_victim = victim_indices.contains(&idx);
            
            if is_victim {
                let is_backrun = attack_type == "backrun";
                let is_sandwich = attack_type == "sandwich";
                let is_parent_round = round == parent_round;
                let exclusion_prob;
                
                if is_backrun || is_sandwich {
                    // For backrunning/sandwiching, we MUST include the victim
                    exclusion_prob = 0.0;
                } else {
                    // MAXIMUM AGGRESSIVENESS strategy for frontrunning
                    if is_parent_round {
                        if can_exclude_all_parent_round_victims {
                            exclusion_prob = 1.0;
                        } else {
                            let remaining_after_exclusion = parent_round_count - excluded_parent_round_count - 1;
                            exclusion_prob = if remaining_after_exclusion >= quorum_threshold { 0.99 } else { 0.95 };
                        }
                    } else {
                        exclusion_prob = 1.0;
                    }
                }

                // Exclude with calculated probability
                if rng.gen::<f64>() < exclusion_prob {
                    if is_parent_round {
                        excluded_parent_round_count += 1;
                    } else {
                        excluded_non_parent_round_count += 1;
                    }
                    debug!("FISSURE ATTACK: Excluding victim node {} from parent set (round={}, parent_round={}, prob={:.3}, excluded_parent={}, excluded_non_parent={})", 
                           idx.0, round, is_parent_round, exclusion_prob, excluded_parent_round_count, excluded_non_parent_round_count);
                    continue;
                }
            }
            
            // Include this parent
            filtered.insert(idx, (hash, round));
        }

        // Final quorum verification - count only parent-round units for quorum
        let mut remaining_parent_round_count = 0;
        for (_idx, &(_, round)) in filtered.iter() {
            if round == parent_round {
                remaining_parent_round_count += 1;
            }
        }
        
        // Only check parent-round quorum (non-parent-round units don't count for quorum)
        if remaining_parent_round_count < quorum_threshold {
            // Not enough parent-round parents after exclusion, use original
            debug!("FISSURE ATTACK: Parent-round quorum broken ({} < {}), reverting to original candidates", 
                   remaining_parent_round_count, quorum_threshold);
            return Ok(self.candidates.clone());
        }

        Ok(filtered)
    }
}

#[cfg(test)]
mod tests {
    use crate::{
        creation::collector::{ConstraintError, UnitsCollector},
        units::{random_full_parent_units_up_to, Unit},
        NodeCount, NodeIndex,
    };
    use aleph_bft_mock::Hasher64;

    #[test]
    fn initial_fails_without_parents() {
        let n_members = NodeCount(4);
        let units_collector = UnitsCollector::<Hasher64>::new_initial(n_members);

        let err = units_collector
            .prospective_parents(NodeIndex(0))
            .expect_err("should fail without parents");
        assert_eq!(err, ConstraintError::NotEnoughParents);
    }

    #[test]
    fn initial_fails_with_too_few_parents() {
        let n_members = NodeCount(4);
        let mut units_collector = UnitsCollector::new_initial(n_members);
        let units = random_full_parent_units_up_to(0, n_members, 43);
        units_collector.add_unit(&units[0][0]);

        let err = units_collector
            .prospective_parents(NodeIndex(0))
            .expect_err("should fail without parents");
        assert_eq!(err, ConstraintError::NotEnoughParents);
    }

    #[test]
    fn initial_fails_without_own_parent() {
        let n_members = NodeCount(4);
        let mut units_collector = UnitsCollector::new_initial(n_members);
        let units = random_full_parent_units_up_to(0, n_members, 43);
        for unit in units[0].iter().skip(1) {
            units_collector.add_unit(unit);
        }

        let err = units_collector
            .prospective_parents(NodeIndex(0))
            .expect_err("should fail without parents");
        assert_eq!(err, ConstraintError::MissingOwnParent);
    }

    #[test]
    fn initial_successfully_computes_minimal_parents() {
        let n_members = NodeCount(4);
        let mut units_collector = UnitsCollector::new_initial(n_members);
        let units = random_full_parent_units_up_to(0, n_members, 43);
        for unit in units[0].iter().take(3) {
            units_collector.add_unit(unit);
        }

        let parents = units_collector
            .prospective_parents(NodeIndex(0))
            .expect("we should be able to retrieve parents");
        assert_eq!(parents.item_count(), 3);

        let new_units: Vec<_> = units[0]
            .iter()
            .take(3)
            .map(|unit| (unit.hash(), unit.round()))
            .collect();
        let selected_parents: Vec<_> = parents.values().cloned().collect();
        assert_eq!(new_units, selected_parents);
    }

    #[test]
    fn initial_successfully_computes_full_parents() {
        let n_members = NodeCount(4);
        let mut units_collector = UnitsCollector::new_initial(n_members);
        let units = random_full_parent_units_up_to(0, n_members, 43);
        for unit in &units[0] {
            units_collector.add_unit(unit);
        }

        let parents = units_collector
            .prospective_parents(NodeIndex(0))
            .expect("we should be able to retrieve parents");
        assert_eq!(parents.item_count(), 4);

        let new_units: Vec<_> = units[0]
            .iter()
            .map(|unit| (unit.hash(), unit.round()))
            .collect();
        let selected_parents: Vec<_> = parents.values().cloned().collect();
        assert_eq!(new_units, selected_parents);
    }

    #[test]
    fn initial_ignores_future_rounds() {
        let n_members = NodeCount(4);
        let mut units_collector = UnitsCollector::new_initial(n_members);
        let units = random_full_parent_units_up_to(2, n_members, 43);
        for round_units in &units {
            for unit in round_units {
                units_collector.add_unit(unit);
            }
        }

        let parents = units_collector
            .prospective_parents(NodeIndex(0))
            .expect("we should be able to retrieve parents");
        assert_eq!(parents.item_count(), 4);

        let new_units: Vec<_> = units[0]
            .iter()
            .map(|unit| (unit.hash(), unit.round()))
            .collect();
        let selected_parents: Vec<_> = parents.values().cloned().collect();
        assert_eq!(new_units, selected_parents);
    }

    #[test]
    fn following_fails_without_parents() {
        let n_members = NodeCount(4);
        let initial_units_collector = UnitsCollector::<Hasher64>::new_initial(n_members);
        let units_collector = UnitsCollector::from_previous(&initial_units_collector);

        let err = units_collector
            .prospective_parents(NodeIndex(0))
            .expect_err("should fail without parents");
        assert_eq!(err, ConstraintError::NotEnoughParents);
    }

    #[test]
    fn following_fails_with_too_few_parents() {
        let n_members = NodeCount(4);
        let initial_units_collector = UnitsCollector::<Hasher64>::new_initial(n_members);
        let mut units_collector = UnitsCollector::from_previous(&initial_units_collector);
        let units = random_full_parent_units_up_to(1, n_members, 43);
        units_collector.add_unit(&units[1][0]);

        let err = units_collector
            .prospective_parents(NodeIndex(0))
            .expect_err("should fail without parents");
        assert_eq!(err, ConstraintError::NotEnoughParents);
    }

    #[test]
    fn following_fails_with_too_old_parents() {
        let n_members = NodeCount(4);
        let initial_units_collector = UnitsCollector::<Hasher64>::new_initial(n_members);
        let mut units_collector = UnitsCollector::from_previous(&initial_units_collector);
        let units = random_full_parent_units_up_to(0, n_members, 43);
        for unit in &units[0] {
            units_collector.add_unit(unit);
        }

        let err = units_collector
            .prospective_parents(NodeIndex(0))
            .expect_err("should fail without parents");
        assert_eq!(err, ConstraintError::NotEnoughParents);
    }

    #[test]
    fn following_fails_without_own_parent() {
        let n_members = NodeCount(4);
        let initial_units_collector = UnitsCollector::<Hasher64>::new_initial(n_members);
        let mut units_collector = UnitsCollector::from_previous(&initial_units_collector);
        let units = random_full_parent_units_up_to(1, n_members, 43);
        for unit in units[1].iter().skip(1) {
            units_collector.add_unit(unit);
        }

        let err = units_collector
            .prospective_parents(NodeIndex(0))
            .expect_err("should fail without parents");
        assert_eq!(err, ConstraintError::MissingOwnParent);
    }

    #[test]
    fn following_fails_with_too_old_own_parent() {
        let n_members = NodeCount(4);
        let initial_units_collector = UnitsCollector::<Hasher64>::new_initial(n_members);
        let mut units_collector = UnitsCollector::from_previous(&initial_units_collector);
        let units = random_full_parent_units_up_to(1, n_members, 43);
        for unit in units[1].iter().skip(1) {
            units_collector.add_unit(unit);
        }
        units_collector.add_unit(&units[0][0]);

        let err = units_collector
            .prospective_parents(NodeIndex(0))
            .expect_err("should fail without parents");
        assert_eq!(err, ConstraintError::MissingOwnParent);
    }

    #[test]
    fn following_successfully_computes_minimal_parents() {
        let n_members = NodeCount(4);
        let initial_units_collector = UnitsCollector::<Hasher64>::new_initial(n_members);
        let mut units_collector = UnitsCollector::from_previous(&initial_units_collector);
        let units = random_full_parent_units_up_to(1, n_members, 43);
        for unit in units[1].iter().take(3) {
            units_collector.add_unit(unit);
        }

        let parents = units_collector
            .prospective_parents(NodeIndex(0))
            .expect("we should be able to retrieve parents");
        assert_eq!(parents.item_count(), 3);

        let new_units: Vec<_> = units[1]
            .iter()
            .take(3)
            .map(|unit| (unit.hash(), unit.round()))
            .collect();
        let selected_parents: Vec<_> = parents.values().cloned().collect();
        assert_eq!(new_units, selected_parents);
    }

    #[test]
    fn following_successfully_computes_minimal_parents_with_ancient() {
        let n_members = NodeCount(4);
        let initial_units_collector = UnitsCollector::<Hasher64>::new_initial(n_members);
        let mut units_collector = UnitsCollector::from_previous(&initial_units_collector);
        let units = random_full_parent_units_up_to(1, n_members, 43);
        for unit in units[1].iter().take(3) {
            units_collector.add_unit(unit);
        }
        units_collector.add_unit(&units[0][3]);

        let parents = units_collector
            .prospective_parents(NodeIndex(0))
            .expect("we should be able to retrieve parents");
        assert_eq!(parents.item_count(), 4);

        let mut new_units: Vec<_> = units[1]
            .iter()
            .take(3)
            .map(|unit| (unit.hash(), unit.round()))
            .collect();
        new_units.push((units[0][3].hash(), units[0][3].round()));
        let selected_parents: Vec<_> = parents.values().cloned().collect();
        assert_eq!(new_units, selected_parents);
    }

    #[test]
    fn following_successfully_computes_full_parents() {
        let n_members = NodeCount(4);
        let initial_units_collector = UnitsCollector::<Hasher64>::new_initial(n_members);
        let mut units_collector = UnitsCollector::from_previous(&initial_units_collector);
        let units = random_full_parent_units_up_to(1, n_members, 43);
        for unit in &units[1] {
            units_collector.add_unit(unit);
        }

        let parents = units_collector
            .prospective_parents(NodeIndex(0))
            .expect("we should be able to retrieve parents");
        assert_eq!(parents.item_count(), 4);

        let new_units: Vec<_> = units[1]
            .iter()
            .map(|unit| (unit.hash(), unit.round()))
            .collect();
        let selected_parents: Vec<_> = parents.values().cloned().collect();
        assert_eq!(new_units, selected_parents);
    }

    #[test]
    fn following_inherits_units() {
        let n_members = NodeCount(4);
        let mut initial_units_collector = UnitsCollector::<Hasher64>::new_initial(n_members);
        let units = random_full_parent_units_up_to(1, n_members, 43);
        for unit in &units[0] {
            initial_units_collector.add_unit(unit);
        }
        let mut units_collector = UnitsCollector::from_previous(&initial_units_collector);
        for unit in units[1].iter().take(3) {
            units_collector.add_unit(unit);
        }

        let parents = units_collector
            .prospective_parents(NodeIndex(0))
            .expect("we should be able to retrieve parents");
        assert_eq!(parents.item_count(), 4);

        let mut new_units: Vec<_> = units[1]
            .iter()
            .take(3)
            .map(|unit| (unit.hash(), unit.round()))
            .collect();
        new_units.push((units[0][3].hash(), units[0][3].round()));
        let selected_parents: Vec<_> = parents.values().cloned().collect();
        assert_eq!(new_units, selected_parents);
    }
}
