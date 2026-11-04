## Summary

<!-- Brief description of changes -->

## Claim

<!-- Required: copy the claim comment from the issue -->

- **Issue**: Closes #
- **Agent/System**:
- **Branch**:

Follow the checklist in [`COORDINATION.md`](../COORDINATION.md).

## VISION.md Alignment

<!-- How do these changes serve the three pillars? -->

- [ ] **Easy to Use**: Reduces cognitive load or tokens
- [ ] **Easy to Extend**: Simplifies adding or composing tools
- [ ] **Easy to Maintain**: Improves validation, evolution, or pruning

## Verification

```bash
./tk check
./tk run wiki.lint --path wiki
python3 -m unittest discover -s tests
```

- [ ] `./tk check`
- [ ] `./tk run wiki.lint --path wiki`
- [ ] `python3 -m unittest discover -s tests`
- [ ] Rebased on `main`
