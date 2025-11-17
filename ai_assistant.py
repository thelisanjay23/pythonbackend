"""
AI Chat Assistant (Static Version)
Returns predefined answers. If no match, returns "reach admin".
"""

import logging

logger = logging.getLogger(__name__)

# 🔹 STATIC ANSWERS DICTIONARY
STATIC_RESPONSES = {
    "kids program": "We offer gymnastics programs for ages 1.5 to 14 years. Levels include Tiny Tumblers, Little Movers, Junior Gym Stars, Tumble Champs, and Tumble Pro.",
    "pricing": "Kids program pricing starts from ₹9,000 for 3 months. Adult & senior fitness programs are also available.",
    "location": "We have centers at Hennur, Banashankari, Electronic City (Bangalore), and Mysuru.",
    "trial": "You can book a trial class by calling +91 9606023971.",
    "age group": "We teach children from 1.5 years up to 14 years, and adults from 15 to 45 years.",
    "coaches": "Our programs are led by expert coaches including Goutham, Ullas, and Aisha.",
    "contact": "You can contact us at +91 9606023971 or info@tumblegym.in.",
}

def find_static_answer(message: str) -> str:
    """
    Match keywords and return static answers.
    """
    msg = message.lower()

    for key, answer in STATIC_RESPONSES.items():
        if key in msg:
            return answer

    return "reach admin"


# ------------------------------
# MAIN REPLACE FUNCTION
# ------------------------------

async def get_ai_response(user_message: str, conversation_history: list = None) -> str:
    """
    Returns static answer instead of AI.
    """
    try:
        return find_static_answer(user_message)
    except Exception as e:
        logger.error(f"Static chat error: {str(e)}")
        return "reach admin"


async def get_quick_replies() -> list:
    return [
        "Tell me about kids programs",
        "What are the pricing plans?",
        "Where is Tumble Gym located?",
        "How do I book a trial class?",
        "What age groups do you teach?",
        "Tell me about your coaches"
    ]
