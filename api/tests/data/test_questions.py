"""Labeled test questions for RAG evaluation."""

TEST_QUESTIONS = [
    # Bisq 1 Questions
    {
        "question": "How do I vote in the DAO?",
        "expected_version": "Bisq 1",
        "expected_topics": ["dao", "voting"],
        "expected_success": True,
    },
    {
        "question": "What is a Burningman?",
        "expected_version": "Bisq 1",
        "expected_topics": ["dao", "burningman"],
        "expected_success": True,
    },
    {
        "question": "How do security deposits work?",
        "expected_version": "Bisq 1",
        "expected_topics": ["trading", "security"],
        "expected_success": True,
    },
    {
        "question": "What is arbitration in Bisq?",
        "expected_version": "Bisq 1",
        "expected_topics": ["arbitration", "disputes"],
        "expected_success": True,
    },
    {
        "question": "How does the 2-of-2 multisig work?",
        "expected_version": "Bisq 1",
        "expected_topics": ["multisig", "security"],
        "expected_success": True,
    },
    {
        "question": "What is BSQ and how do I get it?",
        "expected_version": "Bisq 1",
        "expected_topics": ["bsq", "dao"],
        "expected_success": True,
    },
    {
        "question": "How do I become an arbitrator?",
        "expected_version": "Bisq 1",
        "expected_topics": ["arbitration", "roles"],
        "expected_success": True,
    },
    {
        "question": "What is the delayed payout transaction?",
        "expected_version": "Bisq 1",
        "expected_topics": ["trading", "security"],
        "expected_success": True,
    },
    {
        "question": "How do I trade altcoins?",
        "expected_version": "Bisq 1",
        "expected_topics": ["trading", "altcoins"],
        "expected_success": True,
    },
    {
        "question": "What is a refund agent?",
        "expected_version": "Bisq 1",
        "expected_topics": ["disputes", "roles"],
        "expected_success": True,
    },
    # Bisq 2 Questions
    {
        "question": "How does Bisq Easy work?",
        "expected_version": "Bisq 2",
        "expected_topics": ["bisq-easy", "trading"],
        "expected_success": True,
    },
    {
        "question": "What is the reputation system?",
        "expected_version": "Bisq 2",
        "expected_topics": ["reputation"],
        "expected_success": True,
    },
    {
        "question": "What is the trade limit in Bisq Easy?",
        "expected_version": "Bisq 2",
        "expected_topics": ["bisq-easy", "limits"],
        "expected_success": True,
    },
    {
        "question": "How do bonded roles work in Bisq 2?",
        "expected_version": "Bisq 2",
        "expected_topics": ["bonded-roles"],
        "expected_success": True,
    },
    {
        "question": "Why is the limit 600 USD?",
        "expected_version": "Bisq 2",
        "expected_topics": ["limits", "bisq-easy"],
        "expected_success": True,
    },
    {
        "question": "How do multiple identities work?",
        "expected_version": "Bisq 2",
        "expected_topics": ["identities", "privacy"],
        "expected_success": True,
    },
    {
        "question": "What are the different trade protocols in Bisq 2?",
        "expected_version": "Bisq 2",
        "expected_topics": ["trade-protocols"],
        "expected_success": True,
    },
    {
        "question": "How do I build reputation as a seller?",
        "expected_version": "Bisq 2",
        "expected_topics": ["reputation", "selling"],
        "expected_success": True,
    },
    {
        "question": "Is Bisq Easy good for novice bitcoin users?",
        "expected_version": "Bisq 2",
        "expected_topics": ["bisq-easy", "beginners"],
        "expected_success": True,
    },
    {
        "question": "What payment methods are supported in Bisq Easy?",
        "expected_version": "Bisq 2",
        "expected_topics": ["payment-methods", "bisq-easy"],
        "expected_success": True,
    },
    # Ambiguous Questions
    {
        "question": "How do I buy Bitcoin?",
        "expected_version": "Unknown",
        "should_clarify": True,
    },
    {
        "question": "How do I create an account?",
        "expected_version": "Unknown",
        "should_clarify": True,
    },
    {
        "question": "What are the fees?",
        "expected_version": "Unknown",
        "should_clarify": True,
    },
    {
        "question": "How long does a trade take?",
        "expected_version": "Unknown",
        "should_clarify": True,
    },
    {
        "question": "Is it safe to use?",
        "expected_version": "Unknown",
        "should_clarify": True,
    },
    # Multi-turn Conversations
    {
        "conversation": [
            {"role": "user", "content": "How do I trade?"},
            {"role": "assistant", "content": "Are you using Bisq 1 or Bisq 2?"},
            {"role": "user", "content": "Bisq 1"},
        ],
        "question": "What payment methods are supported?",
        "expected_version": "Bisq 1",
        "expected_context_awareness": True,
    },
    {
        "conversation": [
            {"role": "user", "content": "I'm trying to use Bisq Easy"},
            {"role": "assistant", "content": "Great! How can I help?"},
        ],
        "question": "How long does a trade take?",
        "expected_version": "Bisq 2",
        "expected_context_awareness": True,
    },
    {
        "conversation": [
            {"role": "user", "content": "I want to vote in the DAO"},
            {"role": "assistant", "content": "Sure, I can help with DAO voting."},
        ],
        "question": "What are the requirements?",
        "expected_version": "Bisq 1",
        "expected_context_awareness": True,
    },
    {
        "conversation": [
            {"role": "user", "content": "How does reputation work?"},
            {"role": "assistant", "content": "Reputation is a trust system in Bisq 2."},
        ],
        "question": "How do I improve mine?",
        "expected_version": "Bisq 2",
        "expected_context_awareness": True,
    },
    {
        "conversation": [
            {"role": "user", "content": "I have an issue with arbitration"},
            {"role": "assistant", "content": "I can help with arbitration issues."},
        ],
        "question": "Who decides the outcome?",
        "expected_version": "Bisq 1",
        "expected_context_awareness": True,
    },
    # General/Cross-Version Questions
    {
        "question": "Is Bisq safe?",
        "expected_version": "General",
        "expected_topics": ["security"],
        "expected_success": True,
    },
    {
        "question": "Who created Bisq?",
        "expected_version": "General",
        "expected_topics": ["history"],
        "expected_success": True,
    },
    {
        "question": "Is Bisq open source?",
        "expected_version": "General",
        "expected_topics": ["open-source"],
        "expected_success": True,
    },
    {
        "question": "What is the Bisq network?",
        "expected_version": "General",
        "expected_topics": ["network"],
        "expected_success": True,
    },
    {
        "question": "How does Bisq protect privacy?",
        "expected_version": "General",
        "expected_topics": ["privacy"],
        "expected_success": True,
    },
    # Edge Cases
    {
        "question": "",
        "expected_version": "Unknown",
        "should_clarify": False,
        "expected_success": False,
    },
    {
        "question": "Hello",
        "expected_version": "Unknown",
        "should_clarify": False,
        "expected_success": False,
    },
    {
        "question": "Thanks!",
        "expected_version": "Unknown",
        "should_clarify": False,
        "expected_success": False,
    },
]

# Questions that should trigger clarification
CLARIFICATION_QUESTIONS = [
    "How do I make a trade?",
    "What are the fees?",
    "How long does it take?",
    "What payment methods are supported?",
    "How do I get started?",
    "Is there a minimum amount?",
    "What are the limits?",
    "How do I cancel a trade?",
    "Where do I find my trades?",
    "How do I contact support?",
]

# Questions that indicate frustration
FRUSTRATION_QUESTIONS = [
    "This isn't working!! I've tried everything!",
    "Why is this so complicated? I'm stuck!",
    "The app is broken and nothing works!!",
    "I'm so frustrated with this process!",
    "Can't figure this out!! Help!!",
    "Why doesn't this work?? I followed all the steps!",
    "This is a waste of time!!",
    "I don't understand why this keeps failing!",
    "Nothing makes sense! I'm lost!",
    "How many times do I have to try this??",
]
