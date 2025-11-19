# Feedback Guide

This guide explains how to provide feedback on the Cartha Subnet Validator.

## Providing Feedback

We value your feedback! There are several ways to share your thoughts:

### 1. Discord

Join our official Discord channels for real-time feedback and discussions:

- **Cartha Subnet Channel**: Share feedback in #cartha-sn35: https://discord.gg/X9YzEbRe
- **Bittensor Channel**: Reach out directly to Cartha/0xMarkets team members: https://discord.com/channels/799672011265015819/1415790978077556906

### 2. GitHub Issues

Use GitHub Issues to report bugs, request features, or provide testnet feedback:

- **Bug Reports** - Report bugs or unexpected behavior in the validator
- **Feature Requests** - Suggest new features or enhancements
- **Testnet Feedback** - Share your testnet validator experience

### 3. Pull Requests

Contribute code improvements:

- Fix bugs
- Add features
- Improve documentation
- Enhance tests

See [CONTRIBUTING.md](../CONTRIBUTING.md) for detailed guidelines.

### 4. Discussions

Use GitHub Discussions for:

- Questions and answers about running validators
- General discussions about validator implementation
- Community ideas and suggestions

## Feedback Categories

### Bug Reports

When reporting a bug, please include:

- **Clear description** of what went wrong
- **Steps to reproduce** the issue
- **Expected vs actual** behavior
- **Environment** information:
  - OS and version
  - Python version
  - `uv` version (if using)
  - Bittensor network (testnet/mainnet)
  - NetUID
- **Logs or error messages** (with debug logging enabled)
- **Validator configuration** (dry-run mode, RPC endpoints, etc.)

### Feature Requests

When requesting a feature, please include:

- **Problem statement** - What problem does this solve?
- **Proposed solution** - How should it work?
- **Use cases** - Specific examples of how validators would use it
- **Priority** - How important is this to you?

### Testnet Feedback

When providing testnet feedback, please include:

- **What you tested** - Which validator features did you try?
- **What worked well** - What went smoothly?
- **Issues encountered** - What problems did you face?
- **Suggestions** - How can we improve the validator experience?
- **Performance observations** - RPC lag, scoring timing, etc.

## Validator-Specific Feedback

### Scoring Issues

If you notice scoring problems:

- Include the epoch version
- Share the weight vector output (if safe to share)
- Describe what seems incorrect
- Compare with expected behavior

### RPC/Replay Issues

If you encounter RPC or replay problems:

- Include chain ID and RPC endpoint (redact sensitive parts)
- Share error messages
- Include relevant log snippets
- Note if using `--use-verified-amounts` or full replay

### Performance Feedback

For performance-related feedback:

- Include timing information from logs
- Note the number of miners being processed
- Share system resources (CPU, memory)
- Compare with previous performance if applicable

## Feedback Best Practices

### Be Specific

- Provide concrete examples
- Include relevant code snippets or logs
- Describe the exact steps you took
- Include command-line arguments used

### Be Constructive

- Focus on the issue, not the person
- Suggest solutions when possible
- Explain the impact of the issue
- Consider security implications

### Be Patient

- Give maintainers time to respond
- Follow up if needed, but be respectful
- Understand that fixes take time
- Remember this is open-source software

## Response Times

We aim to respond to:

- **Critical bugs** (validator crashes, security issues): Within 24 hours
- **General issues**: Within 3-5 business days
- **Feature requests**: Within 1-2 weeks
- **Pull requests**: Within 1 week

## Getting Help

If you need help:

1. Check the [README](../README.md) and [TESTNET_SETUP.md](./TESTNET_SETUP.md)
2. Review [ARCHITECTURE.md](./ARCHITECTURE.md) for implementation details
3. Search existing issues
4. Ask in discussions
5. Open an issue with your question

## Security Issues

For security-related issues, please:

- **Do NOT** open a public issue
- Email security concerns directly to maintainers
- Include detailed information about the vulnerability
- Allow time for a fix before disclosure

## Thank You

Your feedback helps make the Cartha Subnet Validator better. We appreciate your time and effort! 🎉
