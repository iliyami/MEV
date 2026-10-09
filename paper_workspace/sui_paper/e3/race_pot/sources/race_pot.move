/// A shared pot for the testnet ordering experiment. Each race has a number; the first `claim` for
/// the current number succeeds and moves the pot to the next race, and any later claim for the same
/// number aborts. Two equal-price claims sent at once therefore show, on chain, which one the
/// network ordered first: the winner succeeds, the loser fails and still pays gas.
module race_pot::race_pot;

const EAlreadyClaimed: u64 = 0;

public struct Pot has key {
    id: UID,
    next: u64,
    last_winner: address,
}

public struct Claimed has copy, drop {
    race: u64,
    winner: address,
}

fun init(ctx: &mut TxContext) {
    transfer::share_object(Pot { id: object::new(ctx), next: 0, last_winner: @0x0 });
}

public fun claim(pot: &mut Pot, race: u64, ctx: &TxContext) {
    assert!(pot.next == race, EAlreadyClaimed);
    pot.next = race + 1;
    pot.last_winner = ctx.sender();
    sui::event::emit(Claimed { race, winner: ctx.sender() });
}
