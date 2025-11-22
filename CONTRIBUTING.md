# Contributing to Cartha Subnet Validator

Thank you for your interest in contributing to the Cartha Subnet Validator! This guide will help you get started.

## Getting Started

### Prerequisites

- Python 3.11
- [`uv`](https://github.com/astral-sh/uv) package manager
- Git
- Basic understanding of Bittensor and EVM blockchains

### Development Setup

1. **Fork and clone the repository**

   ```bash
   git clone https://github.com/your-username/cartha-subnet-validator.git
   cd cartha-subnet-validator
   ```

2. **Install dependencies**

   ```bash
   uv sync
   ```

3. **Run tests**

   ```bash
   make test
   # or
   uv run pytest
   ```

## Development Workflow

### 1. Find Something to Work On

- Check [open issues](https://github.com/your-org/cartha-subnet-validator/issues)
- Look for `good first issue` labels
- Discuss major changes before starting (open an issue first)

### 2. Create a Branch

```bash
git checkout -b feature/your-feature-name
# or
git checkout -b fix/your-bug-fix
```

### 3. Make Your Changes

- Write clean, readable code
- Follow existing code style
- Add tests for new functionality
- Update documentation as needed

### 4. Run Tests and Linters

```bash
# Run all checks
make test

# Run specific checks
uv run ruff check .
uv run mypy cartha_validator
uv run pytest
```

### 5. Commit Your Changes

- Write clear, descriptive commit messages
- Keep commits focused and atomic
- Reference issue numbers when applicable

Example:

```bash
git commit -m "fix: resolve RPC connection timeout issue

- Add retry logic for RPC calls
- Increase default timeout to 30s
- Fixes #123"
```

### 6. Push and Create Pull Request

```bash
git push origin feature/your-feature-name
```

Then create a pull request on GitHub.

## Code Style

### Python Style

- Follow PEP 8
- Use type hints
- Run `ruff` for linting
- Run `mypy` for type checking

### Code Organization

- Keep functions focused and small
- Add docstrings for public functions
- Use meaningful variable names
- Comment complex logic

### Testing

- Write tests for new features
- Aim for good test coverage
- Test both success and failure cases
- Use fixtures for common test data

## Pull Request Guidelines

### Before Submitting

- [ ] Code follows the project's style guidelines
- [ ] Tests pass locally (`make test`)
- [ ] Documentation is updated
- [ ] Commit messages are clear
- [ ] PR description explains the changes

### PR Description Template

```markdown
## Description
Brief description of changes

## Type of Change
- [ ] Bug fix
- [ ] New feature
- [ ] Documentation update
- [ ] Performance improvement
- [ ] Refactoring

## Testing
How was this tested?

## Related Issues
Closes #123
```

### Review Process

- Maintainers will review your PR
- Address feedback promptly
- Be open to suggestions
- Keep discussions constructive

## Project Structure

```text
cartha-subnet-validator/
├── cartha_validator/     # Main validator code
│   ├── main.py          # Entry point, daemon loop, weekly epoch detection
│   ├── epoch_runner.py  # Single epoch execution orchestration
│   ├── processor.py    # Entry processing, UID resolution, position aggregation
│   ├── indexer.py       # RPC replay logic (Model-1 vault events)
│   ├── scoring.py       # Scoring algorithms with pool weights and temperature
│   ├── weights.py       # Weight normalization and publishing
│   ├── config.py        # Configuration and argument parsing
│   ├── epoch.py         # Weekly epoch boundary helpers
│   ├── logging.py       # ANSI colors and emoji helpers
│   └── register.py      # Registration helpers
├── abis/                # Contract ABIs (vault.json)
├── tests/               # Test suite
├── docs/                # Documentation
│   ├── ARCHITECTURE.md  # Architecture overview
│   ├── COMMANDS.md      # Command reference
│   ├── TESTNET_SETUP.md # Testnet setup guide
│   └── FEEDBACK.md      # Feedback guide
└── pyproject.toml       # Project config
```

## Areas for Contribution

### Code Contributions

- Bug fixes
- Performance improvements
- New features
- Code refactoring
- Test coverage improvements

### Documentation

- Improve existing docs
- Add examples
- Fix typos
- Add tutorials
- Translate documentation

### Test

- Add test cases
- Improve test coverage
- Add integration tests
- Performance benchmarks

## Validator-Specific Guidelines

### RPC Handling

- Always handle RPC errors gracefully
- Use retries with exponential backoff
- Log RPC failures appropriately
- Support both testnet and mainnet

### Scoring Logic

- Keep scoring deterministic
- Document scoring formulas
- Add tests for edge cases
- Consider performance implications
- Ensure expired pool filtering works correctly
- Test weekly epoch boundary detection
- Verify weight caching behavior

### Security

- Never commit secrets or private keys
- Validate all inputs
- Use type hints for safety
- Follow security best practices
- Ensure `--use-verified-amounts` is blocked on mainnet
- Validate RPC endpoint configuration
- Test expired pool filtering
- Verify epoch fallback behavior

## Questions?

- Check the [README](README.md) for general information
- Review [ARCHITECTURE.md](docs/ARCHITECTURE.md) for design details
- Open an issue for questions
- Ask in discussions

## Code of Conduct

All contributors are expected to:

- Be respectful and inclusive
- Provide constructive feedback
- Help others learn
- Follow project guidelines

## Recognition

Contributors are recognized in:

- Release notes
- Project documentation
- GitHub contributors list

Thank you for contributing to Cartha Subnet Validator! 🎉
