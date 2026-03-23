from __future__ import annotations


APP_NAME = "ONCard"
APP_TAGLINE = "Free and Open-Source AI Flashcard Study App"

FILES_TO_CARDS_IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tiff", ".tif"}
FILES_TO_CARDS_SOURCE_LIMITS = {
    "standard": {"max_inputs": 12, "up_to_6": 14, "up_to_9": 18, "up_to_max": 20},
    "force": {"max_inputs": 24, "up_to_6": 19, "up_to_9": 21, "up_to_max": 29},
}


SUBJECT_TAXONOMY = {
    "Mathematics": {
        "core": [
            "Arithmetic",
            "Algebra",
            "Geometry",
            "Trigonometry",
            "Calculus",
            "Statistics",
            "Probability",
        ],
        "subtopics": [
            "Linear Equations",
            "Quadratics",
            "Functions",
            "Graphs",
            "Vectors",
            "Matrices",
            "Limits",
            "Derivatives",
            "Integrals",
            "Distributions",
            "Hypothesis Testing",
        ],
    },
    "Science": {
        "core": ["Chemistry", "Physics", "Biology"],
        "subtopics": [
            "Atomic Structure",
            "Periodic Table",
            "Chemical Bonding",
            "Stoichiometry",
            "Thermochemistry",
            "Organic Chemistry",
            "Inorganic Chemistry",
            "Electrochemistry",
            "Reaction Kinetics",
            "Mechanics",
            "Kinematics",
            "Dynamics",
            "Work, Energy, Power",
            "Waves",
            "Optics",
            "Electricity",
            "Magnetism",
            "Thermodynamics",
            "Modern Physics",
            "Cell Biology",
            "Genetics",
            "Evolution",
            "Ecology",
            "Human Anatomy",
            "Physiology",
            "Microbiology",
            "Biotechnology",
        ],
    },
    "Social Studies": {
        "core": ["History", "Geography", "Civics / Politics", "Economics"],
        "subtopics": [
            "Ancient Civilizations",
            "Medieval History",
            "Modern History",
            "Wars",
            "Revolutions",
            "Empires",
            "Physical Geography",
            "Climate",
            "Maps & Cartography",
            "Population",
            "Resources",
            "Government Systems",
            "Democracy",
            "Laws",
            "Rights & Responsibilities",
            "Supply & Demand",
            "Markets",
            "Trade",
            "Inflation",
            "GDP",
            "Microeconomics",
            "Macroeconomics",
        ],
    },
    "Languages": {
        "core": [
            "Grammar",
            "Vocabulary",
            "Reading Comprehension",
            "Writing",
            "Speaking",
            "Listening",
        ],
        "subtopics": [
            "Essays",
            "Letters",
            "Reports",
            "Creative Writing",
            "Literature Analysis",
            "Poetry",
            "Drama",
        ],
    },
    "Computer Science / IT": {
        "core": [
            "Programming",
            "Algorithms",
            "Data Structures",
            "Databases",
            "Networking",
            "Cybersecurity",
            "AI / ML Basics",
        ],
        "subtopics": [
            "Python / C++ / Java",
            "Arrays, Stacks, Queues",
            "Sorting Algorithms",
            "OOP",
            "Web Dev Basics",
            "Operating Systems",
        ],
    },
}


PERFORMANCE_THRESHOLDS = {
    "poor": (10.0, 25.0, "Performance: Poor"),
    "normal": (26.0, 37.0, "Performance: Normal"),
    "smooth": (38.0, 80.0, "Performance: Smooth. No Lag"),
    "best": (81.0, 9999.0, "Performance: Best Tier"),
}


CREATE_RESPONSE_SCHEMA = {
    "type": "object",
    "properties": {
        "title": {"type": "string"},
        "subject": {"type": "string"},
        "category": {"type": "string"},
        "subtopic": {"type": "string"},
        "hints": {"type": "array", "items": {"type": "string"}, "minItems": 3, "maxItems": 5},
        "answer": {"type": "string"},
        "natural_difficulty": {"type": "integer", "minimum": 1, "maximum": 10},
        "response_to_user": {"type": "string"},
    },
    "required": [
        "title",
        "subject",
        "category",
        "subtopic",
        "hints",
        "answer",
        "natural_difficulty",
        "response_to_user",
    ],
}


GRADE_RESPONSE_SCHEMA = {
    "type": "object",
    "properties": {
        "marks_out_of_10": {"type": "number", "minimum": 0, "maximum": 10},
        "state": {"type": "string", "enum": ["correct", "wrong"]},
        "answer_summary": {"type": "string"},
        "what_went_bad": {"type": "string"},
        "what_went_good": {"type": "string"},
        "what_to_improve": {"type": "string"},
    },
    "required": ["marks_out_of_10", "state", "answer_summary", "what_went_bad", "what_went_good"],
}


def files_to_cards_question_schema(question_count: int) -> dict:
    return {
        "type": "object",
        "properties": {
            "questions": {
                "type": "array",
                "items": {"type": "string"},
                "minItems": question_count,
                "maxItems": question_count,
            }
        },
        "required": ["questions"],
    }
