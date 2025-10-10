# Test Suite for Bisq2 Support Agent API

## Overview

This directory contains the test suite for the Bisq2 Support Agent API, providing comprehensive test coverage for critical path functionality across the application's core services.

## Test Infrastructure

### Configuration Files

- **`conftest.py`** - Pytest configuration and shared fixtures
  - Test settings with isolated test environment
  - Service fixtures with mocked dependencies
  - Sample data fixtures for consistent testing
  - Utility fixtures for common test scenarios

- **`pytest.ini`** - Pytest configuration
  - Test discovery patterns
  - Output formatting options
  - Markers for test categorization (unit, integration, slow)
  - Asyncio configuration

### Test Coverage

#### 1. FAQ Repository Tests (`test_faq_repository.py`)

Tests for `FAQRepository` - critical path data integrity testing:

- **Atomic Operations** (TestFAQRepositoryAtomic)
  - Concurrent write consistency
  - File locking and corruption prevention
  - Atomic update rollback on failure

- **Data Validation** (TestFAQRepositoryValidation)
  - Required field validation
  - FAQ retrieval by ID
  - Update ID preservation
  - Deletion operations

- **Filtering** (TestFAQRepositoryFiltering)
  - Category filtering
  - Bisq version filtering
  - Text search functionality

- **Error Handling** (TestFAQRepositoryErrorHandling)
  - Missing file graceful handling
  - Corrupted file recovery
  - Non-existent FAQ handling

#### 2. Feedback Service Tests (`test_feedback_service.py`)

Tests for `FeedbackService` - feedback management and analysis:

- **Storage** (TestFeedbackStorage)
  - Feedback file creation
  - Append operations
  - Data integrity preservation
  - Retrieval operations

- **Statistics** (TestFeedbackStatistics)
  - Basic statistics calculation
  - Enhanced statistics with trends
  - Count accuracy validation
  - Empty feedback handling

- **Filtering** (TestFeedbackFiltering)
  - Positive/negative rating filters
  - Date range filtering
  - Text search functionality

- **Pagination** (TestFeedbackPagination)
  - Page size validation
  - Multi-page navigation

- **Issue Detection** (TestFeedbackIssueDetection)
  - Verbosity issue detection
  - Technical complexity detection
  - Specificity issue detection

- **Weight Management** (TestFeedbackWeightManagement)
  - Initial weight configuration
  - Dynamic weight adjustment

- **Prompt Optimization** (TestFeedbackPromptOptimization)
  - Guidance updates with feedback
  - Insufficient feedback handling

#### 3. RAG Service Tests (`test_rag_service.py`)

Tests for `SimplifiedRAGService` - core RAG functionality:

- **Initialization** (TestRAGServiceInitialization)
  - Service setup verification
  - LLM provider initialization
  - Embeddings initialization

- **Query Processing** (TestRAGQueryProcessing)
  - Known topic queries
  - Unknown topic fallback
  - Chat history inclusion
  - Empty/whitespace query handling

- **Document Retrieval** (TestDocumentRetrieval)
  - Relevant document retrieval
  - Version-aware prioritization
  - Source type weighting

- **Chat History Formatting** (TestChatHistoryFormatting)
  - Empty history handling
  - Message formatting
  - History length limits

- **Prompt Management** (TestPromptManagement)
  - RAG prompt creation
  - Context-only prompt creation
  - Feedback guidance integration

- **Error Handling** (TestErrorHandling)
  - LLM error recovery
  - Retrieval error recovery
  - Empty context handling

- **Document Processing** (TestDocumentProcessing)
  - Context string formatting
  - Max context length enforcement
  - Empty document list handling

## Test Fixtures

### Session-Scoped Fixtures

- `test_data_dir` - Temporary directory for test data (auto-cleanup)
- `test_settings` - Isolated test settings configuration

### Function-Scoped Fixtures

- `test_client` - FastAPI test client
- `sample_faq_data` - Sample FAQ entries for testing
- `sample_feedback_data` - Sample feedback entries for testing
- `faq_service` - Initialized FAQService with sample data
- `feedback_service` - Initialized FeedbackService with sample data
- `rag_service` - SimplifiedRAGService with mocked LLM
- `mock_llm` - Mocked LLM for testing without API calls
- `mock_embeddings` - Mocked embeddings model
- `clean_test_files` - Automatic test file cleanup

## Running Tests

### All Tests
```bash
cd api
pytest tests/
```

### Specific Test File
```bash
pytest tests/test_faq_repository.py
```

### Specific Test Class
```bash
pytest tests/test_feedback_service.py::TestFeedbackStorage
```

### Specific Test Method
```bash
pytest tests/test_rag_service.py::TestRAGQueryProcessing::test_query_with_known_topic
```

### With Coverage
```bash
pytest tests/ --cov=app --cov-report=html
```

### By Marker
```bash
pytest tests/ -m unit          # Run only unit tests
pytest tests/ -m integration   # Run only integration tests
pytest tests/ -m "not slow"    # Skip slow tests
```

## Test Markers

- `@pytest.mark.unit` - Fast, isolated unit tests
- `@pytest.mark.integration` - Integration tests (may require external services)
- `@pytest.mark.slow` - Tests that take >1s to execute

## Current Status

### Test Infrastructure
✅ Pytest configuration complete
✅ Comprehensive fixtures created
✅ 58 test cases written covering critical paths
⚠️ Tests need API compatibility fixes (see Known Issues)

### Coverage Goals
- **Target**: 60% code coverage minimum
- **Priority Areas**:
  - FAQ repository operations
  - Feedback storage and analysis
  - RAG query processing
  - Document retrieval and formatting

## Known Issues

### API Compatibility
Some tests were written based on assumed APIs and need updates to match actual implementations:

1. **FAQRepository** - Tests assume `save_faq()` method, actual is `add_faq()`
2. **FeedbackService** - `store_feedback()` takes dict parameter, not individual kwargs
3. **SimplifiedRAGService** - Some internal methods may differ from test assumptions

### Next Steps
1. Update test method calls to match actual service APIs
2. Fix fixture initialization to provide correct dependencies (e.g., file_lock for FAQRepository)
3. Add missing import statements for Pydantic models
4. Run tests and fix remaining compatibility issues
5. Add pytest-cov for coverage reporting
6. Set up CI/CD integration for automated testing

## Test Writing Guidelines

### Structure
```python
class TestFeatureArea:
    """Test suite for specific feature area."""

    def test_specific_behavior(self, fixture1, fixture2):
        """Test description explaining what is being tested."""
        # Arrange - Set up test data and conditions
        ...

        # Act - Execute the code being tested
        ...

        # Assert - Verify expected outcomes
        assert actual == expected
```

### Best Practices
1. **One assertion per test** - Test one specific behavior
2. **Clear test names** - `test_verb_condition_expected_outcome`
3. **Use fixtures** - Leverage shared fixtures for consistency
4. **Mock external dependencies** - Don't make real API calls
5. **Test edge cases** - Empty inputs, None values, boundaries
6. **Test error conditions** - Exception handling and recovery

### Example
```python
def test_store_feedback_creates_file(self, test_settings, clean_test_files):
    """Test that storing feedback creates the monthly file."""
    # Arrange
    service = FeedbackService(settings=test_settings)

    # Act
    service.store_feedback({
        "question": "Test question?",
        "answer": "Test answer",
        "helpful": True,
    })

    # Assert
    feedback_dir = Path(test_settings.FEEDBACK_DIR_PATH)
    files = list(feedback_dir.glob("feedback_*.jsonl"))
    assert len(files) == 1
```

## Contributing

When adding new tests:
1. Follow existing test structure and naming conventions
2. Use appropriate fixtures from `conftest.py`
3. Add new fixtures to `conftest.py` if needed for reuse
4. Update this README with new test coverage
5. Ensure tests are isolated and don't depend on execution order
6. Run the full test suite before committing

## Resources

- [Pytest Documentation](https://docs.pytest.org/)
- [FastAPI Testing](https://fastapi.tiangolo.com/tutorial/testing/)
- [Testing Best Practices](https://docs.python-guide.org/writing/tests/)
