# Contributing

## Workflow

1. Create a focused branch from `main`.
2. Run the checks relevant to the change:
   - `python scripts/check_doc_pairs.py`
   - `ruff check backend tests`
   - `mypy backend/app`
   - `cd frontend; npm run build; npm run lint; npm run e2e:typecheck`
3. Use synthetic data only. Do not add credentials, personal data, or real supplier/customer records.
4. Open a pull request against `main` and state the acceptance evidence and any unverified boundary.

## Language rules

- Public documents are paired. Chinese canonical files use `*.md` and pair with `*.en.md`; the English canonical `README.en.md` pairs with `README.md`. `LICENSE`, third-party content, and generated content are exempt.
- First-party full-line code comments use Chinese. Inline comments, docstrings, and API documentation stay in their existing language.
- CI runs `scripts/check_doc_pairs.py`; keep it passing.

## Commit style

- Keep commits small and explain the change.
- Do not commit `.env` files, `.local/` contents, tokens, or screenshots containing secrets.

## License

By contributing, you agree that your contributions are licensed under the repository's `LICENSE`.
