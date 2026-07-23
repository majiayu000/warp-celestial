## Summary

Describe the user-visible change and why it is needed.

## Verification

- [ ] `bash -n install.sh`
- [ ] `python3 scripts/check_compatibility.py`
- [ ] `python3 -m unittest discover -s tests -v`
- [ ] `cargo check --locked`
- [ ] `cargo test --locked`
- [ ] Renderer patch applies/reverses and Metal compiles, when applicable
- [ ] Real visual evidence and GPU measurements attached, when applicable
- [ ] English and Chinese documentation updated
- [ ] `CHANGELOG.md` updated

## Safety

- [ ] No credentials, signing material, private paths, or terminal content
- [ ] No unbounded shader loop or increased default ray-step limit
- [ ] No unrelated settings are overwritten or silently ignored
