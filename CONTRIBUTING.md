# Contributing to Enterprise RAG Pipeline

Thank you for your interest in contributing to the Enterprise RAG Pipeline! This document provides guidelines and instructions for contributing.

## Getting Started

1. Fork the repository
2. Clone your fork: `git clone https://github.com/YOUR_USERNAME/enterprise-rag-pipeline.git`
3. Create a feature branch: `git checkout -b feature/your-feature-name`
4. Install development dependencies: `pip install -r requirements.txt`

## Development Workflow

### Setting Up Your Environment

```bash
# Create a virtual environment
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt

# Install development tools
pip install pytest black flake8 mypy
```

### Code Style

- Follow PEP 8 guidelines
- Use type hints for all functions
- Format code with `black`: `black src/ main.py`
- Lint with `flake8`: `flake8 src/ main.py`
- Type check with `mypy`: `mypy src/`

### Testing

- Write unit tests for new features
- Run tests: `pytest tests/ -v`
- Maintain test coverage above 80%

### Commit Messages

Use clear, descriptive commit messages:

```
feat: Add semantic boundary detection for chunking
fix: Resolve MMR filtering edge case
docs: Update deployment guide
test: Add tests for hybrid retriever
```

## Types of Contributions

### Bug Reports

- Check if the bug has already been reported
- Provide a clear description and reproduction steps
- Include Python version, OS, and relevant dependencies

### Feature Requests

- Describe the use case and expected behavior
- Explain how it aligns with the project goals
- Consider implementation complexity

### Documentation

- Improve clarity and completeness
- Add examples and use cases
- Fix typos and formatting

### Code Contributions

- Keep changes focused and minimal
- Add tests for new functionality
- Update documentation as needed
- Ensure all tests pass

## Pull Request Process

1. Update documentation to reflect changes
2. Add or update tests as necessary
3. Ensure all tests pass: `pytest tests/ -v`
4. Run code quality checks: `black`, `flake8`, `mypy`
5. Create a descriptive pull request with:
   - Clear title and description
   - Reference to related issues
   - Summary of changes

## Code of Conduct

- Be respectful and inclusive
- Welcome diverse perspectives
- Provide constructive feedback
- Report inappropriate behavior

## Questions?

- Open an issue for questions or discussions
- Check existing documentation and issues first
- Be patient and respectful in all interactions

Thank you for contributing! 🚀
