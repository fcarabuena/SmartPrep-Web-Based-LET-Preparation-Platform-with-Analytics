"""LET content structure: categories -> courses -> topics (idempotent seeding)."""
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Category, Course, Topic

CURRICULUM = [
    {
        "code": "gen_ed",
        "name": "General Education",
        "description": "Language, mathematics, science and social science competencies for all LET takers.",
        "courses": [
            ("English", None, ["Grammar and Usage", "Vocabulary and Reading Comprehension", "Literature", "Communication Skills"]),
            ("Filipino", None, ["Gramatika at Retorika", "Pag-unawa sa Binasa", "Panitikang Filipino"]),
            ("Mathematics", None, ["Number Sense and Operations", "Algebra", "Geometry and Measurement", "Statistics and Probability"]),
            ("Science", None, ["Biology", "Chemistry", "Physics", "Earth and Space Science"]),
            ("Social Science", None, ["Philippine History", "Philippine Government and Constitution", "Economics", "Society, Culture and Ethics"]),
        ],
    },
    {
        "code": "prof_ed",
        "name": "Professional Education",
        "description": "Pedagogy, curriculum, assessment and the teaching profession.",
        "courses": [
            ("Foundations of Education", None, ["Philosophical Foundations", "Historical Foundations", "Legal Bases of Philippine Education", "The Teaching Profession and Ethics"]),
            ("Theories of Learning", None, ["Behaviorism", "Cognitivism", "Constructivism", "Human Development and Motivation"]),
            ("Curriculum Development", None, ["Curriculum Concepts and Types", "Curriculum Design Models", "Curriculum Implementation and Evaluation"]),
            ("Assessment of Learning", None, ["Principles of Assessment", "Test Construction", "Statistics in Assessment", "Authentic Assessment and Rubrics"]),
            ("Classroom Management", None, ["Discipline Approaches", "Routines and Learning Environment", "Managing Diverse Learners"]),
            ("Teaching Methods", None, ["Principles of Teaching", "Instructional Strategies", "Educational Technology", "Lesson Planning"]),
        ],
    },
    {
        "code": "major",
        "name": "Specialization (Major Core)",
        "description": "Major-specific content for BSEd reviewees.",
        "courses": [
            ("Mathematics Major", "math", ["Advanced Algebra and Number Theory", "Calculus", "Geometry and Trigonometry", "Probability and Statistics"]),
            ("English Major", "english", ["Linguistics", "Literature in English", "Language Teaching Approaches"]),
            ("Filipino Major", "filipino", ["Linggwistika", "Panitikan", "Pagtuturo ng Filipino"]),
            ("Science/Biology Major", "science", ["Cell Biology and Genetics", "Ecology", "Human Anatomy and Physiology", "Evolution and Biodiversity"]),
            ("Social Studies Major", "social_studies", ["World History", "Geography", "Economics and Development", "Philippine Politics and Governance"]),
            ("TLE Major", "tle", ["Home Economics", "Industrial Arts", "Information and Communications Technology", "Agri-Fishery Arts", "Entrepreneurship"]),
        ],
    },
]


def seed_curriculum(db: Session) -> dict[str, int]:
    """Create any missing categories/courses/topics. Safe to run repeatedly."""
    created = {"categories": 0, "courses": 0, "topics": 0}
    for ci, cat_data in enumerate(CURRICULUM):
        cat = db.scalar(select(Category).where(Category.code == cat_data["code"]))
        if cat is None:
            cat = Category(code=cat_data["code"], name=cat_data["name"], description=cat_data["description"], sort_order=ci)
            db.add(cat)
            db.flush()
            created["categories"] += 1
        for co_i, (course_name, major, topics) in enumerate(cat_data["courses"]):
            course = db.scalar(select(Course).where(Course.category_id == cat.id, Course.name == course_name))
            if course is None:
                course = Course(category_id=cat.id, name=course_name, major=major, sort_order=co_i)
                db.add(course)
                db.flush()
                created["courses"] += 1
            for t_i, topic_name in enumerate(topics):
                exists = db.scalar(select(Topic.id).where(Topic.course_id == course.id, Topic.name == topic_name))
                if exists is None:
                    db.add(Topic(course_id=course.id, name=topic_name, sort_order=t_i))
                    created["topics"] += 1
    db.commit()
    return created
