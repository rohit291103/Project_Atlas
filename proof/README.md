# The Phase 2B proof

Harness: `scripts/proof.py`. Design and rubric: `preregistration.md` (a draft until locked).

```bash
python -m scripts.proof prepare                    # prompts per feature, from features.json + specs/
python -m scripts.proof lock                       # once; refuses to re-lock
python -m scripts.proof run --repo ~/src/ripgrep   # costs tokens; resumable
python -m scripts.proof blind --seed <n>           # packets.json for graders; key.json stays sealed
# graders write grades.json: [{"packet_id": "...", "scores": {"behaviour": 3, ...}}]
python -m scripts.proof score --rubric proof/rubric.json
```
