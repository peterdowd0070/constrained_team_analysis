# Mathematical model

## Player event distribution

For hitter `i`, estimate one categorical distribution over
`{K, other out, BB, HBP, 1B, 2B, 3B, HR}` from projected **counts**:
`p_i(e)=projected_event_count / sum(projected_counts)`.
The model currently folds sac flies, fielder's choice outs, and other
non-strikeout outs into OUT; reaches on error, double plays, and complicated
transitions are omitted by the fallback.

## State and transition

A state is `s=(outs in {0,1,2}, bases in {0..7}, next_hitter in {0..8})`,
so 216 transient states. Bits 1,2,4 denote first, second, third base.

For event `e` and pre-state `s`, let `A_e(s',r|s)` give the
conditional distribution over next base/out state and immediate runs.

The full lineup-conditioned transition kernel is

`P(s',r|s,pi) = sum_e p_{pi(k)}(e) A_e(s',r|s)`.

On recording the third out, the inning terminates, bases clear and
the next batter slot carries into the next inning.

## Exact innings

Partition the transient-to-transient transition matrix `Q`,
the transient-to-inning-ending next-hitter matrix `H`,
and expected immediate runs `g`.

`v = (I-Q)^(-1) g` gives run value to inning end.
`F = (I-Q)^(-1) H` gives the next-inning leadoff distribution.

For each inning, sample-free propagation of the nine-component leadoff
distribution gives expected runs. Nine innings sum to nine-inning offense.
This is RE24-style state valuation augmented with lineup slot, not RE24
added on top of already-scored runs.

## Scope and caveats

Nine offensive innings, no opponent pitcher model, no substitutions, no
extra innings, no walk-offs. The default advancement kernel uses deterministic
fixed runner advances and one-out OUTs. It is an engineering baseline only.
The optional Statcast adapter is an unvalidated empirical approximation.
Lineup/roster algorithms use local search and may miss better feasible orders.
