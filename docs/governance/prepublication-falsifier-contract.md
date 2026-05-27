# Prepublication Falsifier Contract

## Roles

- `builder`: prepares the immutable candidate packet and cannot award publication.
- `prepublication-conductor`: orchestration only; dispatches auditors and combines verdicts mechanically.
- `claim-adversary`: single-agent fallback for narrow lanes only.
- `publication-truth-adversary`: attacks chronology, boundary naming, status vocabulary, and retrospective prepublication language.
- `specialist adversaries`: read-only hostile auditors for one failure domain each.
- `publication-authorized actor`: may push only after admitted canonical evidence exists.
- `remote-main reviewer`: independent post-publication verifier.

## Verdict lattice

- any `falsified_blocking` result inside the declared boundary forces `prepublication_blocked`
- any material assertion required for the requested status that remains `unproven_material` forces `prepublication_inconclusive`
- only full satisfaction of all required attack domains without blocking findings permits `prepublication_admitted`
- any boundary-name inflation that exceeds the proven capability is a blocker until the boundary is renamed or the evidence is broadened

## Packet invariants

- the prepublication packet is immutable during review
- the packet contains `candidate_checkpoint_sha`, `candidate_base_remote_sha`, `intended_publication_ref`, `changed_file_slice`, `working_tree_exclusions`, and `boundary_claim_atoms`
- the packet must not contain a remote publication SHA before push
- specialists receive the same immutable packet digest
- the conductor does not rewrite specialist findings
- a prepublication disposition is invalid if it is emitted after the candidate is pushed and described as prepublication admission
