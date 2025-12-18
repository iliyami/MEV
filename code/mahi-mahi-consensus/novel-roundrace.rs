// Novel Round Racing Attack Implementation
// This code replaces the existing roundrace strategy

// ROUND RACING ATTACK: Novel strategy to exploit round-based ordering
// Core insight: Blocks are ordered by (round, authority, digest)
// Higher rounds = Earlier position in consensus order
// Strategy: Race to advance rounds faster than victim
if attack_mode == "speculative" && is_attacker && speculative_strategy == "roundrace" {
    tracing::info!("🚀 ROUND RACING: Novel attack - racing to higher rounds");
    
    let own_prev = includes[0];
    let current_round = own_prev.round;
    let target_round = current_round.saturating_sub(1); // Round for quorum
    
    // Count blocks by round to understand quorum status
    let mut round_counts = std::collections::HashMap::new();
    for include in includes.iter() {
        *round_counts.entry(include.round).or_insert(0) += 1;
    }
    
    tracing::debug!("🚀 Round distribution: {:?}", round_counts);
    
    // Categorize blocks strategically
    let mut quorum_blocks = Vec::new();
    let mut victim_blocks = Vec::new();
    let mut other_blocks = Vec::new();
    let mut future_blocks = Vec::new(); // Blocks from higher rounds
    
    for include in includes.iter().skip(1) {
        if include.round > current_round {
            // These are from the future - shouldn't happen but handle it
            future_blocks.push(*include);
        } else if include.round == target_round {
            // These blocks contribute to quorum for advancing rounds
            quorum_blocks.push(*include);
        } else if include.authority == victim_id {
            victim_blocks.push(*include);
        } else {
            other_blocks.push(*include);
        }
    }
    
    // Novel ordering strategy for round racing:
    // 1. Own previous (required first)
    // 2. ALL quorum blocks (maximize round advancement speed)
    // 3. Future blocks if any (maintain connectivity)
    // 4. Victim blocks FIRST in remaining (LIFO disadvantage)
    // 5. Other blocks LAST (LIFO advantage)
    
    includes.clear();
    includes.push(own_prev);
    
    // Include ALL quorum blocks to advance rounds as fast as possible
    // This is KEY to the round racing attack
    includes.extend(quorum_blocks.clone());
    includes.extend(future_blocks); // Unlikely but handle them
    
    // For LIFO traversal: victim blocks first (processed last)
    includes.extend(victim_blocks);
    includes.extend(other_blocks);
    
    tracing::info!(
        "🚀 ROUND RACING: Round {}, {} quorum blocks (round {}), {} total includes - racing ahead!",
        current_round, quorum_blocks.len(), target_round, includes.len()
    );
}

// HYBRID QUORUM MANIPULATION: Control round advancement timing
// Novel approach: Manipulate which blocks form quorum to control round timing
if attack_mode == "speculative" && is_attacker && speculative_strategy == "quorum" {
    tracing::info!("⚡ QUORUM MANIPULATION: Controlling round advancement");
    
    let own_prev = includes[0];
    let current_round = own_prev.round;
    let target_round = current_round.saturating_sub(1);
    
    // Count authorities in target round for quorum calculation
    let mut target_round_authorities = std::collections::HashSet::new();
    let mut target_blocks = Vec::new();
    let mut other_blocks = Vec::new();
    
    for include in includes.iter().skip(1) {
        if include.round == target_round {
            target_round_authorities.insert(include.authority);
            target_blocks.push(*include);
        } else {
            other_blocks.push(*include);
        }
    }
    
    let quorum_size = (target_round_authorities.len() * 2) / 3 + 1; // 2f+1
    tracing::debug!(
        "⚡ Target round {} has {} unique authorities, quorum needs {}",
        target_round, target_round_authorities.len(), quorum_size
    );
    
    // Strategic selection: Include just enough for quorum, prioritizing non-victim
    let mut selected_quorum = Vec::new();
    let mut victim_quorum = Vec::new();
    
    for block in target_blocks {
        if block.authority == victim_id {
            victim_quorum.push(block);
        } else if selected_quorum.len() < quorum_size {
            selected_quorum.push(block);
        }
    }
    
    // Add victim blocks only if needed for quorum
    while selected_quorum.len() < quorum_size && !victim_quorum.is_empty() {
        selected_quorum.push(victim_quorum.pop().unwrap());
    }
    
    // Rebuild with strategic ordering
    includes.clear();
    includes.push(own_prev);
    includes.extend(selected_quorum);
    includes.extend(other_blocks);
    
    tracing::info!(
        "⚡ QUORUM MANIPULATION: Selected {} of {} available quorum blocks",
        selected_quorum.len(), target_blocks.len()
    );
}

// DIGEST CRAFTING ATTACK: Manipulate block content for favorable digest
// For same (round, authority), lower digest wins
if attack_mode == "speculative" && is_attacker && speculative_strategy == "digest" {
    tracing::info!("🎲 DIGEST CRAFTING: Optimizing block digest");
    
    let own_prev = includes[0];
    
    // Strategy: Minimize our digest by controlling what we include
    // Digest = Blake2b(authority, round, includes, statements, time, epoch, signature)
    
    // Sort includes by their digest to minimize our hash
    let mut sorted_includes: Vec<_> = includes.iter().skip(1).copied().collect();
    sorted_includes.sort_by_key(|b| b.digest);
    
    // Rebuild includes with digest optimization
    includes.clear();
    includes.push(own_prev);
    includes.extend(sorted_includes);
    
    // Note: In production, we could also:
    // 1. Manipulate statements to get lower digest
    // 2. Time our block creation precisely
    // 3. Retry with different nonces if protocol allowed
    
    tracing::info!("🎲 DIGEST CRAFTING: Optimized include ordering for minimal digest");
}




